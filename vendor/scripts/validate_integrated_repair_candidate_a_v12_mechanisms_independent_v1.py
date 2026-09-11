#!/usr/bin/env python3
"""Independent resolver for Candidate A v1.2 mechanism necessity.

This module deliberately does not import the production predicate module.  It
rebuilds every counterfactual MILP from the unchanged v1.1 kernel and performs
its own truth-table reduction and witness-action checks.
"""

from __future__ import annotations

import importlib
from typing import Any


VERSION = "candidate_a_v12_mechanism_independent_resolver_v1"
SOC_A = "SOC_PRETARGET_CHARGE_INCREASE_WITH_FIXED_ROUTES"
SOC_B = "SOC_JOINT_PRETARGET_CHARGE_AND_ROUTE_ADAPTATION"
COMPOSED_A = (
    "COMPOSED_EDGE_AVOIDING_REROUTE_AND_PRETARGET_CHARGE_WITH_FIXED_DEPARTURES"
)
COMPOSED_B = (
    "COMPOSED_EDGE_AVOIDING_REROUTE_PRETARGET_CHARGE_AND_DEPARTURE_RETIMING"
)
SOLVED = "FEASIBLE"
NO_SOLUTION = "PROVEN_INFEASIBLE"
UNRESOLVED = "UNKNOWN"
BROKEN = "ERROR"


def _baseline_rows(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = plan.get("decisions")
    if not isinstance(rows, list):
        raise ValueError("BASELINE_DECISIONS_MISSING")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("mission_id"), str):
            raise ValueError("BASELINE_DECISION_INVALID")
        result[row["mission_id"]] = row
    return result


def _append_row(
    core: Any,
    matrix: Any,
    lower: Any,
    upper: Any,
    values: dict[int, float],
    lo: float,
    hi: float,
) -> tuple[Any, Any, Any]:
    vector = core.np.zeros(matrix.shape[1])
    for column, value in values.items():
        vector[column] = value
    matrix = core.vstack(
        [matrix, core.csr_matrix(vector.reshape(1, -1))], format="csr"
    )
    return (
        matrix,
        core.np.append(lower, lo),
        core.np.append(upper, hi),
    )


def _solver_class(status: Any, success: Any) -> str:
    if isinstance(status, bool) or not isinstance(status, int):
        return BROKEN
    if status == 0 and success is True:
        return SOLVED
    if status == 2 and success is False:
        return NO_SOLUTION
    if status in {1, 3}:
        return UNRESOLVED
    return BROKEN


def _extract(
    core: Any, instance: dict[str, Any], built: dict[str, Any], vector: Any
) -> list[dict[str, Any]]:
    rows = []
    for mission in instance["missions"]:
        mission_id = mission["mission_id"]
        if vector[built["hold_idx"][mission_id]] > 0.5:
            rows.append(
                {
                    "mission_id": mission_id,
                    "uav_id": mission["uav_id"],
                    "held": True,
                    "path_id": None,
                    "depart_slot": None,
                    "charge_blocks": 0,
                }
            )
            continue
        chosen = [
            column
            for column in built["option_indices"][mission_id]
            if vector[column] > 0.5
        ]
        if len(chosen) != 1:
            raise RuntimeError("INDEPENDENT_OPTION_EXTRACTION_INVALID:" + mission_id)
        option = built["var_meta"][chosen[0]]
        rows.append(
            {
                "mission_id": mission_id,
                "uav_id": mission["uav_id"],
                "held": False,
                "path_id": option["path_id"],
                "depart_slot": option["depart_slot"],
                "charge_blocks": option["charge_blocks"],
            }
        )
    return rows


def _actions(
    core: Any,
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    decisions: list[dict[str, Any]],
    pair: dict[str, Any],
) -> dict[str, Any]:
    original = _baseline_rows(baseline)
    repaired = {row["mission_id"]: row for row in decisions}
    mission_by_id = {row["mission_id"]: row for row in instance["missions"]}
    soc = pair["soc"]
    target = mission_by_id[soc["soc_target_mission_id"]]
    target_uav = soc["uav_id"]
    prior_ids = [
        row["mission_id"]
        for row in instance["missions"]
        if row["uav_id"] == target_uav
        and row["sequence_index"] < target["sequence_index"]
    ]
    uav_ids = [
        row["mission_id"]
        for row in instance["missions"]
        if row["uav_id"] == target_uav
    ]
    charge_delta = sum(
        int(repaired[mid]["charge_blocks"]) - int(original[mid]["charge_blocks"])
        for mid in prior_ids
    )
    route_delta = sum(
        repaired[mid].get("path_id") != original[mid].get("path_id")
        for mid in uav_ids
    )
    departure_delta = sum(
        repaired[mid].get("depart_slot") != original[mid].get("depart_slot")
        for mid in uav_ids
    )
    designated_route_changed = None
    if isinstance(pair.get("route"), dict):
        route_mission_id = pair["route"]["mission_id"]
        designated_route_changed = (
            repaired[route_mission_id].get("path_id")
            != original[route_mission_id].get("path_id")
        )
    plan = core.make_plan(
        instance, intervention, "independent_mechanism_certificate", decisions
    )
    activity = core.plan_activity(instance, plan, intervention)
    margins = [
        float(activity["soc_margin"][mid])
        for mid in uav_ids
        if mid in activity.get("soc_margin", {})
        and not repaired[mid].get("held")
    ]
    return {
        "signed_pre_target_charge_block_delta": charge_delta,
        "target_uav_route_change_count": route_delta,
        "target_uav_departure_change_count": departure_delta,
        "designated_route_target_changed": designated_route_changed,
        "minimum_soc_margin_kwh": min(margins) if margins else None,
        "all_served": all(not row.get("held") for row in decisions),
        "witness_plan_sha256": plan["plan_sha256"],
    }


def independent_counterfactual(
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    pair: dict[str, Any],
    kind: str,
    time_limit: float = 20.0,
) -> dict[str, Any]:
    try:
        core = importlib.import_module("integrated_repair_phase_minus1d_core_v1")
        built = core.build_model(instance, intervention, baseline)
        matrix, lower, upper = built["A"], built["lb"], built["ub"]
        original = _baseline_rows(baseline)
        mission_by_id = {row["mission_id"]: row for row in instance["missions"]}
        soc = pair["soc"]
        target_uav = soc["uav_id"]
        target = mission_by_id[soc["soc_target_mission_id"]]

        # A mechanism certificate is always an all-served repair certificate.
        for mission in instance["missions"]:
            matrix, lower, upper = _append_row(
                core,
                matrix,
                lower,
                upper,
                {built["hold_idx"][mission["mission_id"]]: 1.0},
                0.0,
                0.0,
            )

        if kind == "charge_disabled":
            for mission in instance["missions"]:
                if (
                    mission["uav_id"] != target_uav
                    or mission["sequence_index"] >= target["sequence_index"]
                ):
                    continue
                mission_id = mission["mission_id"]
                terms = {
                    index: float(built["var_meta"][index]["charge_blocks"])
                    for index in built["option_indices"][mission_id]
                }
                required = float(original[mission_id]["charge_blocks"])
                matrix, lower, upper = _append_row(
                    core, matrix, lower, upper, terms, required, required
                )
        elif kind == "routes_fixed":
            for mission in instance["missions"]:
                if mission["uav_id"] != target_uav:
                    continue
                mission_id = mission["mission_id"]
                prohibited = {
                    index: 1.0
                    for index in built["option_indices"][mission_id]
                    if built["var_meta"][index]["path_id"]
                    != original[mission_id]["path_id"]
                }
                if prohibited:
                    matrix, lower, upper = _append_row(
                        core, matrix, lower, upper, prohibited, 0.0, 0.0
                    )
        elif kind == "route_disabled":
            route = pair.get("route")
            if not isinstance(route, dict):
                raise ValueError("INDEPENDENT_COMPOSED_ROUTE_TARGET_MISSING")
            mission_id = route["mission_id"]
            prohibited = {
                index: 1.0
                for index in built["option_indices"][mission_id]
                if built["var_meta"][index]["path_id"]
                != original[mission_id]["path_id"]
            }
            if prohibited:
                matrix, lower, upper = _append_row(
                    core, matrix, lower, upper, prohibited, 0.0, 0.0
                )
        elif kind == "departures_fixed":
            for mission in instance["missions"]:
                if mission["uav_id"] != target_uav:
                    continue
                mission_id = mission["mission_id"]
                weighted = {
                    index: float(built["var_meta"][index]["depart_slot"])
                    for index in built["option_indices"][mission_id]
                }
                required = float(original[mission_id]["depart_slot"])
                matrix, lower, upper = _append_row(
                    core, matrix, lower, upper, weighted, required, required
                )
        elif kind != "full":
            raise ValueError("INDEPENDENT_COUNTERFACTUAL_UNSUPPORTED:" + kind)

        count = len(built["var_meta"])
        result = core.milp(
            core.np.zeros(count),
            integrality=core.np.ones(count),
            bounds=core.Bounds(core.np.zeros(count), core.np.ones(count)),
            constraints=core.LinearConstraint(matrix, lower, upper),
            options={
                "time_limit": float(time_limit),
                "mip_rel_gap": 0.0,
                "presolve": True,
            },
        )
        classification = _solver_class(int(result.status), bool(result.success))
        decisions = (
            _extract(core, instance, built, result.x)
            if classification == SOLVED
            else None
        )
        action = (
            _actions(core, instance, intervention, baseline, decisions, pair)
            if decisions is not None
            else None
        )
        return {
            "counterfactual": kind,
            "classification": classification,
            "solver_status": int(result.status),
            "solver_success": bool(result.success),
            "solver_message": str(result.message),
            "decisions": decisions,
            "action_evidence": action,
            "variable_count": count,
            "constraint_count": int(matrix.shape[0]),
            "kernel_version": core.CORE_VERSION,
        }
    except Exception as exc:
        return {
            "counterfactual": kind,
            "classification": BROKEN,
            "solver_status": None,
            "solver_success": False,
            "solver_message": str(exc),
            "exception_type": type(exc).__name__,
            "decisions": None,
            "action_evidence": None,
        }


def _evidence_is_valid(
    row: Any,
    route_mode: str,
    departure_mode: str,
    designated_route_required: bool,
) -> bool:
    if not isinstance(row, dict):
        return False
    action = row.get("action_evidence")
    if not isinstance(action, dict) or action.get("all_served") is not True:
        return False
    charge = action.get("signed_pre_target_charge_block_delta")
    route = action.get("target_uav_route_change_count")
    departure = action.get("target_uav_departure_change_count")
    margin = action.get("minimum_soc_margin_kwh")
    if (
        isinstance(charge, bool)
        or not isinstance(charge, int)
        or charge < 1
        or isinstance(route, bool)
        or not isinstance(route, int)
        or isinstance(departure, bool)
        or not isinstance(departure, int)
        or not isinstance(margin, (int, float))
        or float(margin) < -1e-9
    ):
        return False
    if route_mode == "changed" and route < 1:
        return False
    if route_mode == "unchanged" and route != 0:
        return False
    if designated_route_required and action.get(
        "designated_route_target_changed"
    ) is not True:
        return False
    if departure_mode == "changed" and departure < 1:
        return False
    if departure_mode == "unchanged" and departure != 0:
        return False
    return True


def independent_reduce(
    family: str, counterfactuals: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    required = (
        ("full", "charge_disabled", "routes_fixed")
        if family == "soc_degradation_repair"
        else ("full", "charge_disabled", "route_disabled", "departures_fixed")
        if family == "composed_resource_repair"
        else ()
    )
    if not required:
        return {
            "classification": BROKEN,
            "selected_mechanism": None,
            "reason": "UNSUPPORTED_FAMILY",
        }
    if any(name not in counterfactuals for name in required):
        return {
            "classification": BROKEN,
            "selected_mechanism": None,
            "reason": "COUNTERFACTUAL_MISSING",
        }
    classes = {
        name: counterfactuals[name].get("classification", BROKEN)
        for name in required
    }
    if any(value not in {SOLVED, NO_SOLUTION, UNRESOLVED, BROKEN} for value in classes.values()):
        return {
            "classification": BROKEN,
            "selected_mechanism": None,
            "reason": "CLASSIFICATION_INVALID",
            "classes": classes,
        }
    if BROKEN in classes.values():
        return {
            "classification": BROKEN,
            "selected_mechanism": None,
            "reason": "COUNTERFACTUAL_ERROR",
            "classes": classes,
        }
    if UNRESOLVED in classes.values():
        return {
            "classification": UNRESOLVED,
            "selected_mechanism": None,
            "reason": "COUNTERFACTUAL_UNKNOWN",
            "classes": classes,
        }
    if classes["full"] != SOLVED:
        return {
            "classification": "FALSE",
            "selected_mechanism": None,
            "reason": "FULL_DOMAIN_INFEASIBLE",
            "classes": classes,
        }
    if classes["charge_disabled"] != NO_SOLUTION:
        return {
            "classification": "FALSE",
            "selected_mechanism": None,
            "reason": "CHARGING_NOT_NECESSARY",
            "classes": classes,
        }

    if family == "soc_degradation_repair":
        if classes["routes_fixed"] == SOLVED:
            label, witness, route_mode = SOC_A, "routes_fixed", "unchanged"
        else:
            label, witness, route_mode = SOC_B, "full", "changed"
        departure_mode = "any"
        designated_route_required = False
    else:
        if classes["route_disabled"] != NO_SOLUTION:
            return {
                "classification": "FALSE",
                "selected_mechanism": None,
                "reason": "REROUTE_NOT_NECESSARY",
                "classes": classes,
            }
        if classes["departures_fixed"] == SOLVED:
            label, witness, departure_mode = (
                COMPOSED_A,
                "departures_fixed",
                "unchanged",
            )
        else:
            label, witness, departure_mode = COMPOSED_B, "full", "changed"
        route_mode = "changed"
        designated_route_required = True

    if not _evidence_is_valid(
        counterfactuals[witness],
        route_mode,
        departure_mode,
        designated_route_required,
    ):
        return {
            "classification": BROKEN,
            "selected_mechanism": None,
            "candidate_mechanism": label,
            "reason": "CERTIFICATE_ACTION_WITNESS_INVALID",
            "classes": classes,
        }
    return {
        "classification": "TRUE",
        "selected_mechanism": label,
        "witness_counterfactual": witness,
        "reason": "INDEPENDENT_NECESSITY_CERTIFIED",
        "classes": classes,
    }


def independent_certificate(
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    pair: dict[str, Any],
    time_limit: float = 20.0,
) -> dict[str, Any]:
    family = pair.get("family")
    names = (
        ("full", "charge_disabled", "routes_fixed")
        if family == "soc_degradation_repair"
        else ("full", "charge_disabled", "route_disabled", "departures_fixed")
        if family == "composed_resource_repair"
        else ()
    )
    evidence = {
        name: independent_counterfactual(
            instance, intervention, baseline, pair, name, time_limit
        )
        for name in names
    }
    reduction = independent_reduce(str(family), evidence)
    return {
        "version": VERSION,
        "family": family,
        "pair_id": pair.get("pair_id"),
        "generator_declared_mechanism_ignored": True,
        "counterfactuals": evidence,
        "reduction": reduction,
        "selected_mechanism": reduction.get("selected_mechanism"),
        "accepted": reduction.get("classification") == "TRUE",
    }
