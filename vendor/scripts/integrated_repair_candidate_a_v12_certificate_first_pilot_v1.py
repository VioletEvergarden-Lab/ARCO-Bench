#!/usr/bin/env python3
"""Certificate-first Candidate A v1.2 objective/mechanism development pilot.

This is development-only. It keeps the frozen v1.1 optimization core and
formal verifier, but replaces intent-first parent generation with explicit
construction of (1) a parent-level necessary-mechanism certificate and (2) a
pair of legal repairs whose first lexicographic difference is L4, L5, or L6.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


VERSION = "candidate_a_v12_certificate_first_pilot_v1"
UAV_TYPES = ("fixed_wing_vtol_cargo_uav", "multirotor_cargo_uav")
MECHANISMS = (
    "SOC_PRETARGET_CHARGE_INCREASE_WITH_FIXED_ROUTES",
    "SOC_JOINT_PRETARGET_CHARGE_AND_ROUTE_ADAPTATION",
    "COMPOSED_EDGE_AVOIDING_REROUTE_AND_PRETARGET_CHARGE_WITH_FIXED_DEPARTURES",
    "COMPOSED_EDGE_AVOIDING_REROUTE_PRETARGET_CHARGE_AND_DEPARTURE_RETIMING",
)
ROLES = {
    "L4_WEIGHTED_TARDINESS_PREFIX_CONTROL": (3, "weighted_tardiness_min", 5.0),
    "L5_DELAY_CHARGE_WAIT_PREFIX_CONTROL": (4, "delay_and_charge_wait_min", 5.0),
    "L6_ENERGY_PREFIX_CONTROL": (5, "energy_kwh", 0.05),
}
TIERS = (
    "urgent_holds",
    "total_holds",
    "repair_distance",
    "weighted_tardiness_min",
    "delay_and_charge_wait_min",
    "energy_kwh",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_LOAD_FAILED:" + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules(repo: Path) -> dict[str, Any]:
    scripts = repo / "scripts"
    sys.path.insert(0, str(scripts))
    return {
        "core": load_path("cf_core", scripts / "integrated_repair_phase_minus1d_core_v1.py"),
        "formal": load_path("cf_formal", scripts / "validate_integrated_repair_phase_minus1d_v1.py"),
        "prod_mechanism": load_path("cf_prod_mech", scripts / "integrated_repair_candidate_a_v12_mechanism_predicates_v1.py"),
        "ind_mechanism": load_path("cf_ind_mech", scripts / "validate_integrated_repair_candidate_a_v12_mechanisms_independent_v1.py"),
        "reduction": load_path("cf_reduction", scripts / "integrated_repair_candidate_a_v11_confirmation_hardening_core_v2.py"),
    }


def corridor_for_slots(
    core: Any,
    scenario_id: str,
    corridor_id: str,
    origin: str,
    destination: str,
    desired_slots: int,
    distance_km: float,
    uav_type: str,
    payload_kg: float = 0.5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for step in range(1, 6000):
        corridor = {
            "corridor_id": corridor_id,
            "from_vertiport": origin,
            "to_vertiport": destination,
            "distance_km": round(distance_km, 6),
            "base_travel_time_min": step / 20.0,
            "altitude_layer": "L120_220",
            "authorized": True,
            "weather_closed": False,
            "no_fly": False,
        }
        path = {
            "path_id": "PATH_" + corridor_id,
            "corridor_ids": [corridor_id],
            "node_sequence": [origin, destination],
        }
        metrics = core.path_metrics(
            path, {corridor_id: corridor}, uav_type, payload_kg, scenario_id
        )
        if metrics["travel_slots"] == desired_slots:
            return corridor, metrics
    raise RuntimeError(f"TRAVEL_SLOT_CONSTRUCTION_FAILURE:{uav_type}:{corridor_id}")


def opaque(prefix: str, cell_key: str, index: int) -> str:
    return prefix + "_" + hashlib.sha256(f"{cell_key}|{index}".encode()).hexdigest()[:12]


def make_fleet_row(core: Any, uav_id: str, uav_type: str, start: str, initial_soc: float) -> dict[str, Any]:
    return {
        "uav_id": uav_id,
        "legacy_vehicle_id": "CERTIFICATE_FIRST_DEVELOPMENT_ONLY",
        "uav_type": uav_type,
        "start_vertiport": start,
        "available_slot": 0,
        "initial_soc_kwh": round(initial_soc, 6),
        **core.UAV_TYPES[uav_type],
    }


def make_mission(
    mission_id: str,
    uav_id: str,
    sequence_index: int,
    origin: str,
    destination: str,
    paths: list[tuple[dict[str, Any], dict[str, Any]]],
    release: int,
    due: int,
) -> dict[str, Any]:
    return {
        "mission_id": mission_id,
        "uav_id": uav_id,
        "sequence_index": sequence_index,
        "origin_vertiport": origin,
        "destination_vertiport": destination,
        "payload_kg": 0.5,
        "priority": "routine",
        "release_slot": release,
        "due_slot": due,
        "preferred_construction_path_id": paths[0][1]["path_id"],
        "path_options": [row[1] for row in paths],
        "incoming_deadhead": None,
        "expected_incoming_origin_vertiport": origin,
    }


def build_cell(
    modules: dict[str, Any], mechanism: str, role: str, uav_type: str, variant: int
) -> dict[str, Any]:
    core = modules["core"]
    target_index, target_name, meaningful_floor = ROLES[role]
    cell_key = f"{mechanism}|{role}|{uav_type}|{variant}"
    private_cell_id = "cf_" + hashlib.sha256(cell_key.encode()).hexdigest()[:20]
    scenario_id = "dev_cf_" + hashlib.sha256((cell_key + "|scenario").encode()).hexdigest()[:20]
    mech_uav = opaque("U", cell_key, 1)
    obj_uav = opaque("U", cell_key, 2)
    ma, mb, mc = [opaque("V", cell_key, i) for i in range(1, 4)]
    oa, ob, oc = [opaque("V", cell_key, i) for i in range(4, 7)]
    scale = (0.96, 1.0, 1.04)[variant % 3]

    def path(index: int, origin: str, destination: str, slots: int, distance: float):
        return corridor_for_slots(
            core,
            scenario_id,
            opaque("C", cell_key, index),
            origin,
            destination,
            slots,
            distance * scale,
            uav_type,
        )

    # Mechanism gadget: copied from the already solver-backed mechanism controls,
    # generalized to both UAV types and opaque public identifiers.
    # The joint SOC mechanism needs route adaptation to be necessary after
    # re-optimizing all allowed charging decisions.  Its baseline therefore
    # uses a plausible long detour whose energy excess is greater than the
    # frozen three-block charging budget; the alternative is shorter but still
    # needs a positive pre-target charge.  Other mechanisms retain the compact
    # two-slot structural control used by their solver-backed fixtures.
    if mechanism == MECHANISMS[1]:
        m_base = path(1, ma, mb, 7, 35.0)
        m_alt = path(2, ma, mb, 2, 2.0)
    else:
        m_base = path(1, ma, mb, 2, 1.2)
        m_alt = path(2, ma, mb, 2, 0.9)
    joint_route = mechanism in {
        MECHANISMS[1], MECHANISMS[2], MECHANISMS[3]
    }
    m_second = path(3, mb, mc, 1, 0.8)
    m_first_paths = [m_base, m_alt] if joint_route else [m_base]
    fixed_departures = mechanism in {MECHANISMS[0], MECHANISMS[2]}
    m_depart2 = 9 if mechanism == MECHANISMS[1] else (4 if fixed_departures else 3)
    m_horizon = 9 if mechanism != MECHANISMS[1] else 14
    cfg = core.UAV_TYPES[uav_type]
    reserve = float(cfg["reserve_kwh"])
    m_baseline_soc = reserve + m_base[1]["energy_kwh"] + m_second[1]["energy_kwh"] + 1.0
    m_min_energy = min(row[1]["energy_kwh"] for row in m_first_paths)
    m_degraded_soc = reserve + m_min_energy + m_second[1]["energy_kwh"] - 0.05

    missions = [
        make_mission(opaque("M", cell_key, 1), mech_uav, 0, ma, mb, m_first_paths, 0, 20),
        make_mission(opaque("M", cell_key, 2), mech_uav, 1, mb, mc, [m_second], m_depart2, 20),
    ]
    baseline_path_ids = [m_base[1]["path_id"], m_second[1]["path_id"]]
    baseline_departures = [0, m_depart2]
    corridors = [row[0] for row in m_first_paths] + [m_second[0]]
    obj_initial_soc = reserve + 8.0
    objective_closures: list[tuple[str, range]] = []

    if target_name == "weighted_tardiness_min":
        o_base = path(10, oa, ob, 2, 1.0)
        o_fast = path(11, oa, ob, 1, 1.0)
        o_slow = path(12, oa, ob, 4, 2.0)
        due = (1, 2, 3)[variant % 3]
        missions.append(make_mission(opaque("M", cell_key, 10), obj_uav, 0, oa, ob, [o_base, o_fast, o_slow], 0, due))
        baseline_path_ids.append(o_base[1]["path_id"])
        baseline_departures.append(0)
        corridors.extend([o_base[0], o_fast[0], o_slow[0]])
        objective_closures.append((o_base[0]["corridor_id"], range(0, 24)))
        horizon = max(m_horizon, 24)
    elif target_name == "delay_and_charge_wait_min":
        o_base = path(20, oa, ob, 2, 1.0)
        o_slow_high = path(21, oa, ob, 14, 8.0)
        o_fast_low = path(22, oa, ob, 2, 1.0)
        o_suffix = path(23, ob, oc, 1, 8.0)
        charge = float(cfg["charge_kwh_per_block"])
        lower = max(
            o_fast_low[1]["energy_kwh"] + o_suffix[1]["energy_kwh"] + 0.05,
            o_slow_high[1]["energy_kwh"] + o_suffix[1]["energy_kwh"] - charge + 0.05,
        )
        upper = o_slow_high[1]["energy_kwh"] + o_suffix[1]["energy_kwh"] - 0.05
        if not lower < upper:
            raise RuntimeError("L5_SOC_INTERVAL_EMPTY:" + cell_key)
        fraction = (0.35, 0.5, 0.65)[variant % 3]
        obj_initial_soc = reserve + lower + fraction * (upper - lower)
        missions.extend(
            [
                make_mission(opaque("M", cell_key, 20), obj_uav, 0, oa, ob, [o_base, o_slow_high, o_fast_low], 0, 14),
                make_mission(opaque("M", cell_key, 21), obj_uav, 1, ob, oc, [o_suffix], 16, 20),
            ]
        )
        baseline_path_ids.extend([o_base[1]["path_id"], o_suffix[1]["path_id"]])
        baseline_departures.extend([0, 16])
        corridors.extend([o_base[0], o_slow_high[0], o_fast_low[0], o_suffix[0]])
        objective_closures.extend(
            [
                (o_base[0]["corridor_id"], range(0, 40)),
                (o_fast_low[0]["corridor_id"], range(0, 12)),
            ]
        )
        horizon = max(m_horizon, 40)
    else:
        o_base = path(30, oa, ob, 2, 1.0)
        o_low = path(31, oa, ob, 2, 1.0)
        o_high = path(32, oa, ob, 2, (3.5, 4.0, 4.5)[variant % 3])
        missions.append(make_mission(opaque("M", cell_key, 30), obj_uav, 0, oa, ob, [o_base, o_low, o_high], 0, 5))
        baseline_path_ids.append(o_base[1]["path_id"])
        baseline_departures.append(0)
        corridors.extend([o_base[0], o_low[0], o_high[0]])
        objective_closures.append((o_base[0]["corridor_id"], range(0, 24)))
        horizon = max(m_horizon, 24)

    fleet = [
        make_fleet_row(core, mech_uav, uav_type, ma, m_baseline_soc),
        make_fleet_row(core, obj_uav, uav_type, oa, obj_initial_soc),
    ]
    vertices = [ma, mb, mc, oa, ob, oc]
    instance: dict[str, Any] = {
        "artifact_flags": [
            "CERTIFICATE_FIRST_DEVELOPMENT_ONLY",
            "NOT_FORMAL_CONFIRMATION",
            "NO_MODEL_API",
        ],
        "instance_version": core.INSTANCE_VERSION,
        "model_version": core.MODEL_VERSION,
        "instance_id": private_cell_id,
        "scenario_id": scenario_id,
        "parent_phase_minus1b_scenario_id": None,
        "parent_scenario_content_sha256": None,
        "parent_skeleton_content_sha256": None,
        "split": "certificate_first_development_only",
        "difficulty": "development_constructive_control",
        "ood_axis": "not_applicable_development",
        "pool_role": "not_a_formal_pool_record",
        "topology_motif": "two_component_certificate_first_control",
        "scenario_family": "soc_degradation_repair" if mechanism.startswith("SOC_") else "composed_resource_repair",
        "preregistered_regime": "binding",
        "slot_min": core.SLOT_MIN,
        "turnaround_slots": core.TURNAROUND_SLOTS,
        "max_charge_blocks": core.MAX_CHARGE_BLOCKS,
        "horizon_slots": horizon,
        "assignment_order_contract": "FIXED_UAV_ASSIGNMENT_AND_FIXED_UAV_ORDER",
        "deadhead_contract": "FIXED_REGISTERED_INCOMING_DEADHEAD_PATH",
        "fleet": fleet,
        "missions": missions,
        "resources": {
            "corridor_capacity_by_slot_default": {row["corridor_id"]: 2 for row in corridors},
            "pad_capacity_by_slot_default": {node: 4 for node in vertices},
            "charger_capacity_by_slot_default": {node: 2 for node in vertices},
        },
        "topology": {
            "vertiports": [
                {"vertiport_id": node, "pad_capacity": 4, "charger_count": 2}
                for node in vertices
            ],
            "corridors": corridors,
        },
        "provenance": {
            "generator_version": VERSION,
            "evidence_role": "CERTIFICATE_FIRST_DEVELOPMENT_ONLY",
            "future_population_ancestor": True,
            "public_identifiers_are_opaque": True,
        },
    }
    instance["structural_signatures"] = core.structural_signatures(instance)
    instance["instance_sha256"] = core.sha256_obj(instance)
    empty = core.empty_intervention(instance)
    empty["intervention_sha256"] = core.sha256_obj(empty)
    decisions = []
    for mission, path_id, depart in zip(missions, baseline_path_ids, baseline_departures):
        decisions.append(
            {
                "mission_id": mission["mission_id"],
                "uav_id": mission["uav_id"],
                "held": False,
                "path_id": path_id,
                "depart_slot": depart,
                "charge_blocks": 0,
            }
        )
    baseline = core.make_plan(instance, empty, "certificate_first_preintervention_baseline", decisions)
    family = instance["scenario_family"]
    closed = list(objective_closures)
    if family == "composed_resource_repair":
        closed.append((m_base[0]["corridor_id"], range(0, horizon)))
    intervention = core.empty_intervention(instance)
    intervention.update(
        {
            "family": family,
            "regime": "binding",
            "baseline_plan_sha256": baseline["plan_sha256"],
            "initial_soc_overrides": [
                {"uav_id": mech_uav, "initial_soc_kwh": round(m_degraded_soc, 6)}
            ],
            "closed_corridor_slots": [
                {"corridor_id": corridor_id, "slot": slot}
                for corridor_id, slots in closed
                for slot in slots
            ],
            "operations": [
                {
                    "type": "certificate_first_constructive_control",
                    "evidence_role": "DEVELOPMENT_PRIVATE_CERTIFICATE",
                }
            ],
            "target_selection_provenance": "solver_certified_first_complete_witness",
            "before_after_allowlisted_diff": [
                {
                    "field": "certificate_first_control",
                    "before": "baseline",
                    "after": "private_constructive_parameters",
                }
            ],
        }
    )
    intervention["intervention_sha256"] = core.sha256_obj(intervention)
    pair = {
        "pair_id": "PAIR_" + hashlib.sha256((cell_key + "|mechanism_pair").encode()).hexdigest()[:20],
        "family": family,
        "soc": {
            "uav_id": mech_uav,
            "uav_type": uav_type,
            "soc_target_mission_id": missions[1]["mission_id"],
            "guard_kwh": 0.05,
        },
        "route": (
            {
                "uav_id": mech_uav,
                "mission_id": missions[0]["mission_id"],
                "baseline_path_id": m_base[1]["path_id"],
                "designated_route_target_path_id": m_base[1]["path_id"],
            }
            if family == "composed_resource_repair"
            else None
        ),
        "generator_declared_mechanism": mechanism,
    }
    pair["pair_payload_sha256"] = core.sha256_obj(pair)
    return {
        "private_cell_id": private_cell_id,
        "cell_key": cell_key,
        "mechanism": mechanism,
        "objective_role": role,
        "uav_type": uav_type,
        "variant": variant,
        "target_layer_index": target_index + 1,
        "target_layer_name": target_name,
        "meaningful_gap_floor": meaningful_floor,
        "mechanism_uav_id": mech_uav,
        "objective_uav_id": obj_uav,
        "instance": instance,
        "baseline": baseline,
        "intervention": intervention,
        "pair": pair,
    }


def decisions_from_solution(core: Any, instance: dict[str, Any], built: dict[str, Any], x: Any) -> list[dict[str, Any]]:
    decisions = []
    for mission in instance["missions"]:
        hold = built["hold_idx"][mission["mission_id"]]
        if x[hold] > 0.5:
            decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0})
            continue
        chosen = [i for i in built["option_indices"][mission["mission_id"]] if x[i] > 0.5]
        if len(chosen) != 1:
            raise RuntimeError("OPTION_EXTRACTION_FAILURE:" + mission["mission_id"])
        option = built["var_meta"][chosen[0]]
        decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": False, "path_id": option["path_id"], "depart_slot": option["depart_slot"], "charge_blocks": option["charge_blocks"]})
    return decisions


def objective_pair(modules: dict[str, Any], cell: dict[str, Any], time_limit: float) -> dict[str, Any]:
    core = modules["core"]
    formal = modules["formal"]
    instance, intervention, baseline = cell["instance"], cell["intervention"], cell["baseline"]
    target = core.solve_sequential(instance, intervention, baseline, time_limit=time_limit, check_alternative=True)
    if target.get("status") != "OPTIMAL":
        raise RuntimeError("TARGET_ORACLE_NOT_OPTIMAL:" + str(target.get("solver_message")))
    built = core.build_model(instance, intervention, baseline)
    names = [name for name, _ in built["tiers"]]
    if tuple(names) != TIERS:
        raise RuntimeError("OBJECTIVE_TIER_DRIFT:" + repr(names))
    values = {row["name"]: float(row["value"]) for row in target["objective_vector"]}
    target_index = cell["target_layer_index"] - 1
    A, lb, ub = built["A"], built["lb"], built["ub"]
    for name, vector in built["tiers"][:target_index]:
        tolerance = 1e-4 if name == "energy_kwh" else 1e-7
        A = core.vstack([A, core.csr_matrix(vector.reshape(1, -1))], format="csr")
        lb = core.np.append(lb, values[name] - tolerance)
        ub = core.np.append(ub, values[name] + tolerance)
    # Keep the mechanism component identical to the target repair. Only the
    # independent objective gadget may vary in the prefix competitor.
    target_map = {row["mission_id"]: row for row in target["decisions"]}
    for mission in instance["missions"]:
        if mission["uav_id"] != cell["mechanism_uav_id"]:
            continue
        decision = target_map[mission["mission_id"]]
        if decision.get("held"):
            index = built["hold_idx"][mission["mission_id"]]
        else:
            index = next(
                i for i in built["option_indices"][mission["mission_id"]]
                if built["var_meta"][i]["path_id"] == decision["path_id"]
                and built["var_meta"][i]["depart_slot"] == decision["depart_slot"]
                and built["var_meta"][i]["charge_blocks"] == decision["charge_blocks"]
            )
        vector = core.np.zeros(len(built["var_meta"]))
        vector[index] = 1.0
        A = core.vstack([A, core.csr_matrix(vector.reshape(1, -1))], format="csr")
        lb = core.np.append(lb, 1.0)
        ub = core.np.append(ub, 1.0)
    target_name, target_vector = built["tiers"][target_index]
    result = core.milp(
        -target_vector,
        integrality=core.np.ones(len(built["var_meta"])),
        bounds=core.Bounds(core.np.zeros(len(built["var_meta"])), core.np.ones(len(built["var_meta"]))),
        constraints=core.LinearConstraint(A, lb, ub),
        options={"time_limit": time_limit, "mip_rel_gap": 0.0, "presolve": True},
    )
    if not (result.success and result.status == 0):
        raise RuntimeError("PREFIX_COMPETITOR_NOT_FOUND:" + str(result.message))
    competitor_decisions = decisions_from_solution(core, instance, built, result.x)
    competitor = core.make_plan(instance, intervention, "certificate_first_prefix_competitor", competitor_decisions)
    target_check = formal.validate_plan(instance, intervention, target, baseline=baseline, oracle=target)
    competitor_check = formal.validate_plan(instance, intervention, competitor, baseline=baseline, oracle=target)
    target_objective = {row["name"]: float(row["value"]) for row in target["objective_vector"]}
    competitor_objective = competitor_check.get("objective") or {}
    earlier = names[:target_index]
    prefix_equal = all(
        abs(float(competitor_objective[name]) - target_objective[name]) <= (1e-4 if name == "energy_kwh" else 1e-7)
        for name in earlier
    )
    gap = float(competitor_objective[target_name]) - target_objective[target_name]
    mechanism_decisions_equal = all(
        target_map[m["mission_id"]] == {row["mission_id"]: row for row in competitor["decisions"]}[m["mission_id"]]
        for m in instance["missions"] if m["uav_id"] == cell["mechanism_uav_id"]
    )
    return {
        "target_plan": target,
        "prefix_competitor_plan": competitor,
        "target_formal_valid": target_check.get("valid") is True,
        "target_formal_errors": target_check.get("errors", []),
        "competitor_formal_valid": competitor_check.get("valid") is True,
        "competitor_formal_errors": competitor_check.get("errors", []),
        "target_objective": target_objective,
        "competitor_objective": competitor_objective,
        "earlier_layers": earlier,
        "prefix_equal": prefix_equal,
        "target_layer_name": target_name,
        "target_layer_gap": gap,
        "meaningful_gap_floor": cell["meaningful_gap_floor"],
        "meaningful_positive_gap": gap >= cell["meaningful_gap_floor"],
        "mechanism_component_decisions_equal": mechanism_decisions_equal,
        "adversarial_solver_status": int(result.status),
        "adversarial_solver_message": str(result.message),
    }


def parent_success(modules: dict[str, Any], cell: dict[str, Any], objective: dict[str, Any], time_limit: float) -> dict[str, Any]:
    core, formal, reduction = modules["core"], modules["formal"], modules["reduction"]
    instance, baseline, intervention, pair = cell["instance"], cell["baseline"], cell["intervention"], cell["pair"]
    empty = core.empty_intervention(instance)
    # The baseline plan was created against the canonical inactive intervention.
    # Preserve that lineage digest, then attach the verifier-required baseline
    # pointer without pretending the pointer was part of the pre-baseline object.
    empty["intervention_sha256"] = core.sha256_obj(empty)
    # The frozen formal verifier requires every intervention, including the
    # inactive no-op control, to carry the actual baseline lineage digest.
    empty["baseline_plan_sha256"] = baseline["plan_sha256"]
    no_op = core.solve_sequential(instance, empty, baseline, time_limit=time_limit, check_alternative=True)
    baseline_check = formal.validate_plan(instance, empty, baseline, baseline=baseline, oracle=None)
    noop_check = formal.validate_plan(instance, empty, no_op, baseline=baseline, oracle=no_op)
    noop_semantic = reduction.noop_semantic_result(
        baseline_check.get("objective"), noop_check.get("objective"),
        {"record_integrity_valid": baseline_check.get("valid") is True and noop_check.get("valid") is True, "integrity_codes": []},
        inactive_intervention=True,
    )
    binding_check = formal.validate_plan(instance, intervention, objective["target_plan"], baseline=baseline, oracle=objective["target_plan"])
    v4 = reduction.binding_v4_result(
        instance, baseline, objective["target_plan"], pair,
        {"record_integrity_valid": binding_check.get("valid") is True, "integrity_codes": []},
    )
    over = copy.deepcopy(intervention)
    # Overcritical is diagnostic and must remain a valid optimization problem.
    # Closing every route of the SOC-target mission forces the canonical hold
    # behavior; driving initial SOC below reserve would instead make even a held
    # plan infeasible and therefore corrupt record integrity.
    missions = {row["mission_id"]: row for row in instance["missions"]}
    soc_target = pair["soc"]["soc_target_mission_id"]
    target_mission = missions[soc_target]
    target_corridors = sorted({
        corridor_id
        for path in target_mission["path_options"]
        for corridor_id in path["corridor_ids"]
    })
    closed = {
        (row["corridor_id"], int(row["slot"]))
        for row in over.get("closed_corridor_slots", [])
    }
    closed.update(
        (corridor_id, slot)
        for corridor_id in target_corridors
        for slot in range(int(instance["horizon_slots"]))
    )
    over["closed_corridor_slots"] = [
        {"corridor_id": corridor_id, "slot": slot}
        for corridor_id, slot in sorted(closed)
    ]
    over["operations"] = list(over.get("operations", [])) + [{"type": "certificate_first_overcritical_control"}]
    over.pop("intervention_sha256", None)
    over["intervention_sha256"] = core.sha256_obj(over)
    over_plan = core.solve_sequential(instance, over, baseline, time_limit=time_limit, check_alternative=True)
    over_check = formal.validate_plan(instance, over, over_plan, baseline=baseline, oracle=over_plan)
    before = {row["mission_id"]: row for row in baseline["decisions"]}
    over_semantic = reduction.overcritical_result(
        {"record_integrity_valid": over_check.get("valid") is True, "integrity_codes": []},
        holds=sum(bool(row.get("held")) for row in over_plan.get("decisions", [])),
        route_changes=sum(before.get(row["mission_id"], {}).get("path_id") != row.get("path_id") for row in over_plan.get("decisions", []) if row["mission_id"] in before),
        charge_changes=sum(before.get(row["mission_id"], {}).get("charge_blocks") != row.get("charge_blocks") for row in over_plan.get("decisions", []) if row["mission_id"] in before),
    )
    passed = bool(
        noop_semantic.get("semantic_pass") is True
        and v4.get("activation_pass") is True
        and over_semantic.get("record_integrity_valid") is True
    )
    return {
        "parent_success": passed,
        "baseline_formal_valid": baseline_check.get("valid") is True,
        "noop_formal_valid": noop_check.get("valid") is True,
        "noop_semantic": noop_semantic,
        "binding_formal_valid": binding_check.get("valid") is True,
        "binding_v4": v4,
        "overcritical_formal_valid": over_check.get("valid") is True,
        "overcritical_semantic": over_semantic,
        "no_op_plan": no_op,
        "overcritical_intervention": over,
        "overcritical_plan": over_plan,
    }


def construct_certificate(modules: dict[str, Any], mechanism: str, role: str, uav_type: str, variant: int, time_limit: float) -> dict[str, Any]:
    started = time.perf_counter()
    cell = build_cell(modules, mechanism, role, uav_type, variant)
    objective = objective_pair(modules, cell, time_limit)
    production = modules["prod_mechanism"].mechanism_certificate(
        cell["instance"], cell["intervention"], cell["baseline"], cell["pair"], time_limit=time_limit
    )
    independent = modules["ind_mechanism"].independent_certificate(
        cell["instance"], cell["intervention"], cell["baseline"], cell["pair"], time_limit=time_limit
    )
    parent = parent_success(modules, cell, objective, time_limit)
    mechanism_ok = bool(
        production.get("accepted") is True
        and independent.get("accepted") is True
        and production.get("selected_mechanism") == mechanism
        and independent.get("selected_mechanism") == mechanism
        and production.get("reduction", {}).get("classification") == "TRUE"
        and independent.get("reduction", {}).get("classification") == "TRUE"
    )
    q2 = [
        {"rank": 1, "role": "TARGET_REPAIR", "plan_sha256": objective["target_plan"]["plan_sha256"]},
        {"rank": 2, "role": "PREFIX_COMPETITOR", "plan_sha256": objective["prefix_competitor_plan"]["plan_sha256"]},
    ]
    admitted = bool(
        mechanism_ok
        and len(q2) == 2
        and objective["target_formal_valid"]
        and objective["competitor_formal_valid"]
        and objective["prefix_equal"]
        and objective["meaningful_positive_gap"]
        and objective["mechanism_component_decisions_equal"]
        and parent["parent_success"]
    )
    private = {
        "version": VERSION + "_private_certificate",
        "evidence_scope": "DEVELOPMENT_ONLY_NOT_FORMAL_CONFIRMATION",
        "cell": {k: cell[k] for k in ("private_cell_id", "mechanism", "objective_role", "uav_type", "variant", "target_layer_index", "target_layer_name")},
        "instance": cell["instance"],
        "baseline": cell["baseline"],
        "intervention": cell["intervention"],
        "selected_pair": cell["pair"],
        "q2_repair_certificates": q2,
        "objective_certificate": objective,
        "production_mechanism_certificate": production,
        "independent_mechanism_certificate": independent,
        "parent_success_certificate": parent,
        "admitted": admitted,
        "runtime_sec": round(time.perf_counter() - started, 6),
    }
    private["certificate_sha256"] = sha_obj(private)
    public_instance = copy.deepcopy(cell["instance"])
    public_instance["provenance"].pop("future_population_ancestor", None)
    public = {
        "version": VERSION + "_public_projection",
        "evidence_scope": "DEVELOPMENT_PUBLIC_PROJECTION_NOT_FORMAL_POOL",
        "public_instance_id": "PUB_" + hashlib.sha256(cell["private_cell_id"].encode()).hexdigest()[:20],
        "instance": public_instance,
        "baseline": cell["baseline"],
        "operational_intervention": cell["intervention"],
        "private_fields_absent": [
            "mechanism_label", "objective_role", "selected_pair", "target_repair", "prefix_competitor", "objective_vectors", "certificate"
        ],
    }
    public["public_projection_sha256"] = sha_obj(public)
    summary = {
        "cell_id": cell["private_cell_id"],
        "mechanism": mechanism,
        "objective_role": role,
        "uav_type": uav_type,
        "variant": variant,
        "admitted": admitted,
        "mechanism_certified": mechanism_ok,
        "q2_count": len(q2),
        "prefix_equal": objective["prefix_equal"],
        "target_layer_name": objective["target_layer_name"],
        "target_layer_gap": objective["target_layer_gap"],
        "meaningful_gap_floor": objective["meaningful_gap_floor"],
        "target_formal_valid": objective["target_formal_valid"],
        "competitor_formal_valid": objective["competitor_formal_valid"],
        "v4_pass": parent["binding_v4"].get("activation_pass") is True,
        "parent_success": parent["parent_success"],
        "production_independent_mechanism_match": production.get("selected_mechanism") == independent.get("selected_mechanism"),
        "runtime_sec": private["runtime_sec"],
        "certificate_sha256": private["certificate_sha256"],
        "public_projection_sha256": public["public_projection_sha256"],
    }
    return {"summary": summary, "private": private, "public": public}


def write_result(output: Path, result: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    private_dir, public_dir = output / "private", output / "public"
    private_dir.mkdir(exist_ok=True)
    public_dir.mkdir(exist_ok=True)
    cell_id = result["summary"]["cell_id"]
    (private_dir / f"{cell_id}.json").write_text(json.dumps(result["private"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (public_dir / f"{result['public']['public_instance_id']}.json").write_text(json.dumps(result["public"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("anchors", "pilot"), required=True)
    parser.add_argument("--time-limit", type=float, default=20.0)
    args = parser.parse_args()
    repo, output = Path(args.repo).resolve(), Path(args.output).resolve()
    modules = load_modules(repo)
    cells = []
    if args.mode == "anchors":
        for role in ROLES:
            for uav_type in UAV_TYPES:
                for variant in range(3):
                    cells.append((MECHANISMS[0], role, uav_type, variant))
    else:
        for mechanism_index, mechanism in enumerate(MECHANISMS):
            for role_index, role in enumerate(ROLES):
                for uav_index, uav_type in enumerate(UAV_TYPES):
                    cells.append((mechanism, role, uav_type, (mechanism_index + role_index + uav_index) % 3))
    rows, failures = [], []
    for index, (mechanism, role, uav_type, variant) in enumerate(cells, 1):
        try:
            result = construct_certificate(modules, mechanism, role, uav_type, variant, args.time_limit)
            write_result(output, result)
            rows.append(result["summary"])
        except Exception as exc:
            failures.append({"index": index, "mechanism": mechanism, "objective_role": role, "uav_type": uav_type, "variant": variant, "exception_type": type(exc).__name__, "message": str(exc)})
        checkpoint = {"version": VERSION + "_checkpoint", "mode": args.mode, "completed": index, "total": len(cells), "admitted": sum(row["admitted"] for row in rows), "failure_count": len(failures)}
        output.mkdir(parents=True, exist_ok=True)
        (output / "CHECKPOINT.json").write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
    summary = {
        "version": VERSION + "_summary",
        "mode": args.mode,
        "cell_count": len(cells),
        "completed_certificate_count": len(rows),
        "admitted_count": sum(row["admitted"] for row in rows),
        "rejected_count": sum(not row["admitted"] for row in rows),
        "exception_count": len(failures),
        "rows": rows,
        "failures": failures,
        "model_api_network_call_count": 0,
        "secret_or_dotenv_read_count": 0,
        "formal_confirmation_count": 0,
        "formal_pool_count": 0,
    }
    summary["summary_sha256"] = sha_obj(summary)
    (output / "PILOT_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": args.mode, "cells": len(cells), "certificates": len(rows), "admitted": summary["admitted_count"], "exceptions": len(failures)}, sort_keys=True))
    return 0 if summary["admitted_count"] == len(cells) and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
