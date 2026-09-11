#!/usr/bin/env python3
"""Parent-level necessary-component predicates for Candidate A v1.2.

The module does not construct parents and never trusts generator mechanism
labels.  A mechanism is classified only from fresh counterfactual solves under
the unchanged Candidate A v1.1 MILP kernel.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any, Callable


VERSION = "candidate_a_v12_parent_level_necessary_mechanism_predicates_v1"
FEASIBLE = "FEASIBLE"
INFEASIBLE = "PROVEN_INFEASIBLE"
UNKNOWN = "UNKNOWN"
ERROR = "ERROR"

SOC_FIXED_ROUTE = "SOC_PRETARGET_CHARGE_INCREASE_WITH_FIXED_ROUTES"
SOC_JOINT_ROUTE = "SOC_JOINT_PRETARGET_CHARGE_AND_ROUTE_ADAPTATION"
COMPOSED_FIXED_DEPART = (
    "COMPOSED_EDGE_AVOIDING_REROUTE_AND_PRETARGET_CHARGE_WITH_FIXED_DEPARTURES"
)
COMPOSED_RETIMING = (
    "COMPOSED_EDGE_AVOIDING_REROUTE_PRETARGET_CHARGE_AND_DEPARTURE_RETIMING"
)

MECHANISMS_BY_FAMILY = {
    "soc_degradation_repair": (SOC_FIXED_ROUTE, SOC_JOINT_ROUTE),
    "composed_resource_repair": (COMPOSED_FIXED_DEPART, COMPOSED_RETIMING),
}

SOC_MARGIN_TOLERANCE_KWH = 1e-9
CHARGE_DELTA_MINIMUM_BLOCKS = 1


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("solver_status")
    success = raw.get("solver_success")
    if isinstance(status, bool) or not isinstance(status, int):
        classification = ERROR
    elif status == 0 and success is True:
        classification = FEASIBLE
    elif status == 2 and success is False:
        classification = INFEASIBLE
    elif status in {1, 3}:
        classification = UNKNOWN
    else:
        classification = ERROR
    return {
        **raw,
        "classification": classification,
        "solution_present": classification == FEASIBLE
        and isinstance(raw.get("decisions"), list),
    }


def _class(value: Any) -> str:
    if not isinstance(value, dict):
        return ERROR
    result = str(value.get("classification", ERROR))
    return result if result in {FEASIBLE, INFEASIBLE, UNKNOWN, ERROR} else ERROR


def _action_ok(
    value: Any,
    *,
    route_required: bool,
    route_forbidden: bool,
    designated_route_required: bool,
    departure_required: bool,
    departure_forbidden: bool,
) -> bool:
    if not isinstance(value, dict):
        return False
    action = value.get("action_evidence")
    if not isinstance(action, dict):
        return False
    charge_ok = (
        isinstance(action.get("signed_pre_target_charge_block_delta"), int)
        and action["signed_pre_target_charge_block_delta"]
        >= CHARGE_DELTA_MINIMUM_BLOCKS
    )
    reserve_ok = (
        isinstance(action.get("minimum_soc_margin_kwh"), (int, float))
        and float(action["minimum_soc_margin_kwh"])
        >= -SOC_MARGIN_TOLERANCE_KWH
    )
    route_count = action.get("target_uav_route_change_count")
    depart_count = action.get("target_uav_departure_change_count")
    if not isinstance(route_count, int) or not isinstance(depart_count, int):
        return False
    if route_required and route_count < 1:
        return False
    if route_forbidden and route_count != 0:
        return False
    if designated_route_required and action.get(
        "designated_route_target_changed"
    ) is not True:
        return False
    if departure_required and depart_count < 1:
        return False
    if departure_forbidden and depart_count != 0:
        return False
    return charge_ok and reserve_ok


def reduce_counterfactuals(
    family: str, counterfactuals: dict[str, Any]
) -> dict[str, Any]:
    """Reduce independently solved counterfactuals to one exclusive label."""

    expected = (
        {"full", "charge_disabled", "routes_fixed"}
        if family == "soc_degradation_repair"
        else {"full", "charge_disabled", "route_disabled", "departures_fixed"}
        if family == "composed_resource_repair"
        else set()
    )
    if not expected:
        return {
            "status": "DEFAULT_DENY_ERROR",
            "classification": ERROR,
            "selected_mechanism": None,
            "codes": ["UNSUPPORTED_FAMILY"],
        }
    missing = sorted(expected - set(counterfactuals))
    if missing:
        return {
            "status": "DEFAULT_DENY_ERROR",
            "classification": ERROR,
            "selected_mechanism": None,
            "codes": ["MISSING_COUNTERFACTUAL:" + name for name in missing],
        }
    classes = {name: _class(counterfactuals[name]) for name in sorted(expected)}
    if any(value == ERROR for value in classes.values()):
        return {
            "status": "DEFAULT_DENY_ERROR",
            "classification": ERROR,
            "selected_mechanism": None,
            "classes": classes,
            "codes": ["COUNTERFACTUAL_ERROR"],
        }
    if any(value == UNKNOWN for value in classes.values()):
        return {
            "status": "DEFAULT_DENY_UNKNOWN",
            "classification": UNKNOWN,
            "selected_mechanism": None,
            "classes": classes,
            "codes": ["COUNTERFACTUAL_UNKNOWN"],
        }
    if classes["full"] != FEASIBLE:
        return {
            "status": "NOT_REPAIRABLE_IN_FULL_DOMAIN",
            "classification": "FALSE",
            "selected_mechanism": None,
            "classes": classes,
            "codes": ["FULL_DOMAIN_NOT_FEASIBLE"],
        }
    if classes["charge_disabled"] != INFEASIBLE:
        return {
            "status": "NO_SUPPORTED_NECESSARY_CHARGING_MECHANISM",
            "classification": "FALSE",
            "selected_mechanism": None,
            "classes": classes,
            "codes": ["PRETARGET_CHARGING_NOT_NECESSARY"],
        }

    selected: str | None = None
    witness_key: str | None = None
    action_valid = False
    codes: list[str] = []
    if family == "soc_degradation_repair":
        if classes["routes_fixed"] == FEASIBLE:
            selected = SOC_FIXED_ROUTE
            witness_key = "routes_fixed"
            action_valid = _action_ok(
                counterfactuals[witness_key],
                route_required=False,
                route_forbidden=True,
                designated_route_required=False,
                departure_required=False,
                departure_forbidden=False,
            )
        elif classes["routes_fixed"] == INFEASIBLE:
            selected = SOC_JOINT_ROUTE
            witness_key = "full"
            action_valid = _action_ok(
                counterfactuals[witness_key],
                route_required=True,
                route_forbidden=False,
                designated_route_required=False,
                departure_required=False,
                departure_forbidden=False,
            )
    else:
        if classes["route_disabled"] != INFEASIBLE:
            return {
                "status": "NO_SUPPORTED_NECESSARY_COMPOSED_MECHANISM",
                "classification": "FALSE",
                "selected_mechanism": None,
                "classes": classes,
                "codes": ["DESIGNATED_REROUTE_NOT_NECESSARY"],
            }
        if classes["departures_fixed"] == FEASIBLE:
            selected = COMPOSED_FIXED_DEPART
            witness_key = "departures_fixed"
            action_valid = _action_ok(
                counterfactuals[witness_key],
                route_required=True,
                route_forbidden=False,
                designated_route_required=True,
                departure_required=False,
                departure_forbidden=True,
            )
        elif classes["departures_fixed"] == INFEASIBLE:
            selected = COMPOSED_RETIMING
            witness_key = "full"
            action_valid = _action_ok(
                counterfactuals[witness_key],
                route_required=True,
                route_forbidden=False,
                designated_route_required=True,
                departure_required=True,
                departure_forbidden=False,
            )

    if selected is None:
        codes.append("CLASSIFICATION_NOT_EXHAUSTIVE")
    if not action_valid:
        codes.append("NECESSARY_COMPONENT_NOT_ACTIVATED_IN_CERTIFICATE_WITNESS")
    if codes:
        return {
            "status": "DEFAULT_DENY_ERROR",
            "classification": ERROR,
            "selected_mechanism": None,
            "candidate_mechanism": selected,
            "witness_counterfactual": witness_key,
            "classes": classes,
            "codes": codes,
        }
    return {
        "status": "MECHANISM_CERTIFIED",
        "classification": "TRUE",
        "selected_mechanism": selected,
        "witness_counterfactual": witness_key,
        "classes": classes,
        "codes": [],
        "mutually_exclusive_by_counterfactual_partition": True,
    }


def _baseline_map(baseline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["mission_id"]: row
        for row in baseline.get("decisions", [])
        if isinstance(row, dict) and isinstance(row.get("mission_id"), str)
    }


def _add_constraint(
    core: Any,
    A: Any,
    lb: Any,
    ub: Any,
    coefficients: dict[int, float],
    low: float,
    high: float,
) -> tuple[Any, Any, Any]:
    row = core.np.zeros(A.shape[1])
    for index, value in coefficients.items():
        row[index] = value
    A = core.vstack([A, core.csr_matrix(row.reshape(1, -1))], format="csr")
    lb = core.np.append(lb, low)
    ub = core.np.append(ub, high)
    return A, lb, ub


def _extract_decisions(
    core: Any, instance: dict[str, Any], built: dict[str, Any], x: Any
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for mission in instance["missions"]:
        hold = built["hold_idx"][mission["mission_id"]]
        if x[hold] > 0.5:
            decisions.append(
                {
                    "mission_id": mission["mission_id"],
                    "uav_id": mission["uav_id"],
                    "held": True,
                    "path_id": None,
                    "depart_slot": None,
                    "charge_blocks": 0,
                }
            )
            continue
        chosen = [
            index
            for index in built["option_indices"][mission["mission_id"]]
            if x[index] > 0.5
        ]
        if len(chosen) != 1:
            raise RuntimeError(
                f"MECHANISM_OPTION_EXTRACTION:{mission['mission_id']}:{chosen}"
            )
        meta = built["var_meta"][chosen[0]]
        decisions.append(
            {
                "mission_id": mission["mission_id"],
                "uav_id": mission["uav_id"],
                "held": False,
                "path_id": meta["path_id"],
                "depart_slot": meta["depart_slot"],
                "charge_blocks": meta["charge_blocks"],
            }
        )
    return decisions


def _action_evidence(
    core: Any,
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    decisions: list[dict[str, Any]],
    pair: dict[str, Any],
) -> dict[str, Any]:
    before = _baseline_map(baseline)
    after = {row["mission_id"]: row for row in decisions}
    missions = {row["mission_id"]: row for row in instance["missions"]}
    soc = pair["soc"]
    target = missions[soc["soc_target_mission_id"]]
    uav_id = soc["uav_id"]
    predecessors = [
        row
        for row in instance["missions"]
        if row["uav_id"] == uav_id
        and row["sequence_index"] < target["sequence_index"]
    ]
    charge_delta = sum(
        int(after[row["mission_id"]]["charge_blocks"])
        - int(before[row["mission_id"]]["charge_blocks"])
        for row in predecessors
    )
    target_rows = [row for row in instance["missions"] if row["uav_id"] == uav_id]
    route_changes = sum(
        before[row["mission_id"]].get("path_id")
        != after[row["mission_id"]].get("path_id")
        for row in target_rows
    )
    departure_changes = sum(
        before[row["mission_id"]].get("depart_slot")
        != after[row["mission_id"]].get("depart_slot")
        for row in target_rows
    )
    plan = core.make_plan(
        instance, intervention, "synthetic_mechanism_certificate_witness", decisions
    )
    activity = core.plan_activity(instance, plan, intervention)
    margins = [
        float(value)
        for mission_id, value in activity.get("soc_margin", {}).items()
        if mission_id in after and not after[mission_id].get("held")
    ]
    route_target_changed = None
    if pair.get("route"):
        mission_id = pair["route"]["mission_id"]
        route_target_changed = (
            before[mission_id].get("path_id") != after[mission_id].get("path_id")
        )
    return {
        "signed_pre_target_charge_block_delta": charge_delta,
        "target_uav_route_change_count": route_changes,
        "target_uav_departure_change_count": departure_changes,
        "designated_route_target_changed": route_target_changed,
        "minimum_soc_margin_kwh": min(margins) if margins else None,
        "all_served": not any(row.get("held") for row in decisions),
        "witness_plan_sha256": plan["plan_sha256"],
    }


def solve_counterfactual(
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    pair: dict[str, Any],
    counterfactual: str,
    time_limit: float = 20.0,
) -> dict[str, Any]:
    """Solve one necessary-component counterfactual using the unchanged kernel."""

    try:
        core = importlib.import_module("integrated_repair_phase_minus1d_core_v1")
        built = core.build_model(instance, intervention, baseline)
        A, lb, ub = built["A"], built["lb"], built["ub"]
        baseline_by_id = _baseline_map(baseline)
        missions = {row["mission_id"]: row for row in instance["missions"]}
        soc = pair["soc"]
        uav_id = soc["uav_id"]
        target = missions[soc["soc_target_mission_id"]]

        for mission in instance["missions"]:
            hold = built["hold_idx"][mission["mission_id"]]
            A, lb, ub = _add_constraint(
                core, A, lb, ub, {hold: 1.0}, 0.0, 0.0
            )

        if counterfactual == "charge_disabled":
            for mission in sorted(
                (
                    row
                    for row in instance["missions"]
                    if row["uav_id"] == uav_id
                    and row["sequence_index"] < target["sequence_index"]
                ),
                key=lambda row: row["sequence_index"],
            ):
                coefficients = {
                    index: float(built["var_meta"][index]["charge_blocks"])
                    for index in built["option_indices"][mission["mission_id"]]
                }
                value = float(
                    baseline_by_id[mission["mission_id"]]["charge_blocks"]
                )
                A, lb, ub = _add_constraint(
                    core, A, lb, ub, coefficients, value, value
                )
        elif counterfactual == "routes_fixed":
            for mission in instance["missions"]:
                if mission["uav_id"] != uav_id:
                    continue
                path_id = baseline_by_id[mission["mission_id"]]["path_id"]
                coefficients = {
                    index: 1.0
                    for index in built["option_indices"][mission["mission_id"]]
                    if built["var_meta"][index]["path_id"] != path_id
                }
                if coefficients:
                    A, lb, ub = _add_constraint(
                        core, A, lb, ub, coefficients, 0.0, 0.0
                    )
        elif counterfactual == "route_disabled":
            if not pair.get("route"):
                raise ValueError("ROUTE_DISABLED_REQUIRES_COMPOSED_PAIR")
            mission_id = pair["route"]["mission_id"]
            path_id = baseline_by_id[mission_id]["path_id"]
            coefficients = {
                index: 1.0
                for index in built["option_indices"][mission_id]
                if built["var_meta"][index]["path_id"] != path_id
            }
            if coefficients:
                A, lb, ub = _add_constraint(
                    core, A, lb, ub, coefficients, 0.0, 0.0
                )
        elif counterfactual == "departures_fixed":
            for mission in instance["missions"]:
                if mission["uav_id"] != uav_id:
                    continue
                coefficients = {
                    index: float(built["var_meta"][index]["depart_slot"])
                    for index in built["option_indices"][mission["mission_id"]]
                }
                value = float(baseline_by_id[mission["mission_id"]]["depart_slot"])
                A, lb, ub = _add_constraint(
                    core, A, lb, ub, coefficients, value, value
                )
        elif counterfactual != "full":
            raise ValueError("UNSUPPORTED_COUNTERFACTUAL:" + counterfactual)

        n = len(built["var_meta"])
        result = core.milp(
            core.np.zeros(n),
            integrality=core.np.ones(n),
            bounds=core.Bounds(core.np.zeros(n), core.np.ones(n)),
            constraints=core.LinearConstraint(A, lb, ub),
            options={
                "time_limit": float(time_limit),
                "mip_rel_gap": 0.0,
                "presolve": True,
            },
        )
        raw: dict[str, Any] = {
            "counterfactual": counterfactual,
            "solver_status": int(result.status),
            "solver_success": bool(result.success),
            "solver_message": str(result.message),
            "decisions": None,
            "action_evidence": None,
            "kernel_version": core.CORE_VERSION,
            "variable_count": n,
            "constraint_count": int(A.shape[0]),
        }
        if result.status == 0 and result.success:
            decisions = _extract_decisions(core, instance, built, result.x)
            raw["decisions"] = decisions
            raw["action_evidence"] = _action_evidence(
                core, instance, intervention, baseline, decisions, pair
            )
        return _normalize(raw)
    except Exception as exc:
        return _normalize(
            {
                "counterfactual": counterfactual,
                "solver_status": None,
                "solver_success": False,
                "solver_message": str(exc),
                "exception_type": type(exc).__name__,
                "decisions": None,
                "action_evidence": None,
            }
        )


SolveFunction = Callable[
    [
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        str,
        float,
    ],
    dict[str, Any],
]


def mechanism_certificate(
    instance: dict[str, Any],
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    pair: dict[str, Any],
    *,
    time_limit: float = 20.0,
    solve_fn: SolveFunction | None = None,
) -> dict[str, Any]:
    family = str(pair.get("family"))
    names = (
        ("full", "charge_disabled", "routes_fixed")
        if family == "soc_degradation_repair"
        else ("full", "charge_disabled", "route_disabled", "departures_fixed")
        if family == "composed_resource_repair"
        else ()
    )
    solve = solve_fn or solve_counterfactual
    evidence = {
        name: solve(instance, intervention, baseline, pair, name, time_limit)
        for name in names
    }
    result = reduce_counterfactuals(family, evidence)
    return {
        "version": VERSION,
        "family": family,
        "pair_id": pair.get("pair_id"),
        "generator_declared_mechanism_ignored": True,
        "counterfactuals": evidence,
        "reduction": result,
        "selected_mechanism": result.get("selected_mechanism"),
        "accepted": result.get("classification") == "TRUE",
    }
