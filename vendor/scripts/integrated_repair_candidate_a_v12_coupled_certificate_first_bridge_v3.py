#!/usr/bin/env python3
"""Development-only V3 coupled certificate-first bridge constructor.

This module overlays the proven objective/mechanism controls with a mixed-fleet
shared-resource coupling and constructs the best mechanism-preserving,
equal-prefix *semantic* alternative under a deterministic no-good condition.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


VERSION = "candidate_a_v12_coupled_certificate_first_bridge_v3"
CONTRACT_VERSION = "candidate_a_v12_coupled_certificate_contract_v3"
TOPOLOGIES = (
    "SHARED_ORIGIN_PAD_CAPACITY",
    "SHARED_DESTINATION_PAD_CAPACITY",
    "SHARED_CORRIDOR_CAPACITY",
)
TARGET_TYPES = ("fixed_wing_vtol_cargo_uav", "multirotor_cargo_uav")
TIERS = (
    "urgent_holds", "total_holds", "repair_distance",
    "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh",
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
    old = load_path("coupled_old", scripts / "integrated_repair_candidate_a_v12_certificate_first_pilot_v1.py")
    modules = old.load_modules(repo)
    modules["old"] = old
    solve_counter = {"subsolves": 0}
    canonical_core = importlib.import_module("integrated_repair_phase_minus1d_core_v1")
    seen: set[int] = set()
    for core_module in (modules["core"], canonical_core):
        if id(core_module) in seen:
            continue
        seen.add(id(core_module))
        original_milp = core_module.milp

        def counted_milp(*args: Any, _original: Any = original_milp, **kwargs: Any) -> Any:
            solve_counter["subsolves"] += 1
            return _original(*args, **kwargs)

        core_module.milp = counted_milp
    modules["solve_counter"] = solve_counter
    return modules


def other_type(value: str) -> str:
    return TARGET_TYPES[1] if value == TARGET_TYPES[0] else TARGET_TYPES[0]


def _mission_sequence(instance: dict[str, Any], uav_id: str) -> list[dict[str, Any]]:
    return sorted((m for m in instance["missions"] if m["uav_id"] == uav_id), key=lambda row: row["sequence_index"])


def _refresh_path(core: Any, instance: dict[str, Any], mission: dict[str, Any], old_path: dict[str, Any]) -> dict[str, Any]:
    corridors = {row["corridor_id"]: row for row in instance["topology"]["corridors"]}
    seed = {
        "path_id": old_path["path_id"],
        "corridor_ids": list(old_path["corridor_ids"]),
        "node_sequence": [mission["origin_vertiport"], mission["destination_vertiport"]],
    }
    return core.path_metrics(seed, corridors, next(u["uav_type"] for u in instance["fleet"] if u["uav_id"] == mission["uav_id"]), mission["payload_kg"], instance["scenario_id"])


def _add_support_suffix(modules: dict[str, Any], cell: dict[str, Any], target_type: str) -> None:
    old, core = modules["old"], modules["core"]
    instance, support_uav = cell["instance"], cell["objective_uav_id"]
    seq = _mission_sequence(instance, support_uav)
    if len(seq) >= 2:
        return
    first = seq[0]
    key = cell["cell_key"] + "|support_suffix"
    new_node = old.opaque("V", key, 91)
    corridor, path = old.corridor_for_slots(
        core, instance["scenario_id"], old.opaque("C", key, 91),
        first["destination_vertiport"], new_node, 1, 1.15 + 0.05 * cell["variant"], other_type(target_type),
    )
    suffix_release = min(8, max(1, int(instance["horizon_slots"]) - 4))
    suffix_due = max(suffix_release + 2, int(instance["horizon_slots"]) - 1)
    mission = old.make_mission(
        old.opaque("M", key, 91), support_uav, 1,
        first["destination_vertiport"], new_node, [(corridor, path)], suffix_release, suffix_due,
    )
    instance["missions"].append(mission)
    instance["topology"]["corridors"].append(corridor)
    instance["topology"]["vertiports"].append({"vertiport_id": new_node, "pad_capacity": 2, "charger_count": 2})
    cell["_support_suffix_baseline"] = {"mission_id": mission["mission_id"], "uav_id": support_uav, "held": False, "path_id": path["path_id"], "depart_slot": suffix_release, "charge_blocks": 0}


def _add_dominated_target_route(modules: dict[str, Any], cell: dict[str, Any]) -> None:
    old, core = modules["old"], modules["core"]
    instance, target_uav = cell["instance"], cell["mechanism_uav_id"]
    mission = _mission_sequence(instance, target_uav)[0]
    if len(mission["path_options"]) >= 2:
        return
    key = cell["cell_key"] + "|target_route_padding"
    corridor, path = old.corridor_for_slots(
        core, instance["scenario_id"], old.opaque("C", key, 92),
        mission["origin_vertiport"], mission["destination_vertiport"], 8, 12.0,
        cell["uav_type"], mission["payload_kg"],
    )
    mission["path_options"].append(path)
    instance["topology"]["corridors"].append(corridor)
    instance["topology"]["vertiports"] = list({row["vertiport_id"]: row for row in instance["topology"]["vertiports"]}.values())


def _add_mechanism_semantic_freedom(
    modules: dict[str, Any], cell: dict[str, Any], role: str, target_type: str,
    variant: int,
) -> None:
    """Add a real, non-baseline route branch for composed mechanisms.

    Both branches remain route adaptations relative to the baseline.  Their
    travel/energy profiles are selected so that the requested objective layer,
    rather than an opaque path identifier, can distinguish them while the
    higher repair-distance prefix remains equal.
    """
    old, core = modules["old"], modules["core"]
    if cell["mechanism"] not in {old.MECHANISMS[1], old.MECHANISMS[2], old.MECHANISMS[3]}:
        return
    instance = cell["instance"]
    mission = _mission_sequence(instance, cell["mechanism_uav_id"])[0]
    baseline_path = next(
        row["path_id"] for row in cell["baseline"]["decisions"]
        if row["mission_id"] == mission["mission_id"]
    )
    available = [p for p in mission["path_options"] if p["path_id"] != baseline_path]
    if not available:
        raise RuntimeError("COMPOSED_PRIMARY_ALTERNATIVE_MISSING")
    primary = min(available, key=lambda p: (p["travel_slots"], p["energy_kwh"], p["path_id"]))
    if cell["mechanism"] == old.MECHANISMS[2]:
        second = _mission_sequence(instance, cell["mechanism_uav_id"])[1]
        second["release_slot"] = 5
        for decision in cell["baseline"]["decisions"]:
            if decision["mission_id"] == second["mission_id"]:
                decision["depart_slot"] = 5
    if role in {"L4_WEIGHTED_TARDINESS_PREFIX_CONTROL", "L5_DELAY_CHARGE_WAIT_PREFIX_CONTROL"}:
        profiles = [
            (int(primary["travel_slots"]) + 1, float(primary["distance_km"]) + 0.08 + 0.02 * (variant % 3), 121),
        ]
    else:
        # The medium route is a decoupled best alternative.  Under corridor
        # coupling it can be blocked at the shared slot, exposing the higher
        # route as the coupled best semantic competitor and mediating L6.
        profiles = [
            (int(primary["travel_slots"]), float(primary["distance_km"]) + 0.16, 121),
            (int(primary["travel_slots"]), float(primary["distance_km"]) + 0.40 + 0.01 * (variant % 3), 122),
        ]
    existing_routes = {tuple(p["corridor_ids"]) for p in mission["path_options"]}
    for slots, distance, index in profiles:
        key = cell["cell_key"] + f"|semantic_branch|{role}|{variant}|{index}"
        corridor, path = old.corridor_for_slots(
            core, instance["scenario_id"], old.opaque("C", key, index),
            mission["origin_vertiport"], mission["destination_vertiport"],
            slots, distance, target_type, mission["payload_kg"],
        )
        if tuple(path["corridor_ids"]) in existing_routes:
            raise RuntimeError("SEMANTIC_BRANCH_ROUTE_COLLISION")
        existing_routes.add(tuple(path["corridor_ids"]))
        mission["path_options"].append(path)
        instance["topology"]["corridors"].append(corridor)


def _balance_public_nuisance_fields(cell: dict[str, Any], role: str) -> None:
    """Use a shared due-date multiset without changing the objective contract."""
    instance = cell["instance"]
    target = _mission_sequence(instance, cell["mechanism_uav_id"])
    support = _mission_sequence(instance, cell["objective_uav_id"])
    connector = next(m for m in support if m["mission_id"] == cell["connector_mission_id"])
    objective = next(m for m in support if m["mission_id"] != connector["mission_id"])
    suffix = support[-1]
    if role == "L4_WEIGHTED_TARDINESS_PREFIX_CONTROL":
        target[0]["priority"] = "urgent"
        target[0]["due_slot"] = 2
        target[1]["due_slot"] = 18
        objective["due_slot"] = 6
        suffix["due_slot"] = 20
        connector["due_slot"] = 23
    else:
        connector["due_slot"] = 2
        target[0]["due_slot"] = 6
        target[1]["due_slot"] = 18
        objective["due_slot"] = 20
        suffix["due_slot"] = 23


def _force_fixed_departure_availability(modules: dict[str, Any], cell: dict[str, Any], intervention: dict[str, Any]) -> None:
    """Encode the already-declared fixed-departure composed mechanism.

    Corridor availability, an existing intervention variable, makes the two
    target-UAV departure events available only at their baseline slots.  This
    prevents the full-domain optimum from silently becoming a retiming repair.
    """
    old = modules["old"]
    if cell["mechanism"] != old.MECHANISMS[2]:
        return
    baseline = {row["mission_id"]: row for row in cell["baseline"]["decisions"]}
    existing = {(row["corridor_id"], int(row["slot"])) for row in intervention.get("closed_corridor_slots", [])}
    horizon = int(cell["instance"]["horizon_slots"])
    for mission in _mission_sequence(cell["instance"], cell["mechanism_uav_id"]):
        depart = int(baseline[mission["mission_id"]]["depart_slot"])
        baseline_path = baseline[mission["mission_id"]]["path_id"]
        for path in mission["path_options"]:
            if path["path_id"] == baseline_path and mission["sequence_index"] == 0:
                continue
            for segment in path["edge_segments"]:
                corridor_id = segment["corridor_id"]
                allowed = set(range(depart + int(segment["offset_slot"]), depart + int(segment["offset_slot"]) + int(segment["duration_slots"])))
                for slot in range(horizon):
                    if slot not in allowed:
                        existing.add((corridor_id, slot))
    intervention["closed_corridor_slots"] = [
        {"corridor_id": corridor_id, "slot": slot}
        for corridor_id, slot in sorted(existing)
    ]


def _force_l5_retiming_pad_mediation(modules: dict[str, Any], cell: dict[str, Any], intervention: dict[str, Any]) -> None:
    """Expose a discrete L5 mediation witness using existing availability semantics.

    For the retiming mechanism only, the second mechanism mission is made
    available at the same pad slot as the fast/no-charge L5 alternative.  The
    coupled solution must resolve the order, while the support suffix can move
    one slot toward its baseline so the L3 prefix remains exactly unchanged.
    """
    old = modules["old"]
    if not (
        cell["mechanism"] == old.MECHANISMS[3]
        and cell["objective_role"] == "L5_DELAY_CHARGE_WAIT_PREFIX_CONTROL"
        and cell["coupling_topology"] == TOPOLOGIES[1]
    ):
        return
    second = _mission_sequence(cell["instance"], cell["mechanism_uav_id"])[1]
    forced_departure = 15
    existing = {(row["corridor_id"], int(row["slot"])) for row in intervention.get("closed_corridor_slots", [])}
    horizon = int(cell["instance"]["horizon_slots"])
    for path in second["path_options"]:
        for segment in path["edge_segments"]:
            allowed = set(range(
                forced_departure + int(segment["offset_slot"]),
                forced_departure + int(segment["offset_slot"]) + int(segment["duration_slots"]),
            ))
            for slot in range(horizon):
                if slot not in allowed:
                    existing.add((segment["corridor_id"], slot))
    intervention["closed_corridor_slots"] = [
        {"corridor_id": corridor_id, "slot": slot}
        for corridor_id, slot in sorted(existing)
    ]


def _rebalance_mechanism_soc_for_semantic_routes(modules: dict[str, Any], cell: dict[str, Any], intervention: dict[str, Any]) -> None:
    """Keep every genuine non-baseline route usable while preserving charge necessity."""
    old, core = modules["old"], modules["core"]
    if cell["mechanism"] == old.MECHANISMS[0]:
        return
    seq = _mission_sequence(cell["instance"], cell["mechanism_uav_id"])
    baseline_path = next(row["path_id"] for row in cell["baseline"]["decisions"] if row["mission_id"] == seq[0]["mission_id"])
    route_energy = [float(p["energy_kwh"]) for p in seq[0]["path_options"] if p["path_id"] != baseline_path]
    suffix_energy = min(float(p["energy_kwh"]) for p in seq[1]["path_options"])
    if len(route_energy) < 2:
        return
    lower = max(route_energy) + 0.02
    upper = min(route_energy) + suffix_energy - 0.02
    if not lower < upper:
        raise RuntimeError("SEMANTIC_ROUTE_SOC_INTERVAL_EMPTY")
    uav_type = next(row["uav_type"] for row in cell["instance"]["fleet"] if row["uav_id"] == cell["mechanism_uav_id"])
    value = float(core.UAV_TYPES[uav_type]["reserve_kwh"]) + (lower + upper) / 2.0
    intervention["initial_soc_overrides"] = [{"uav_id": cell["mechanism_uav_id"], "initial_soc_kwh": round(value, 6)}]


def build_coupled_cell(modules: dict[str, Any], mechanism: str, role: str, target_type: str, variant: int, topology: str) -> dict[str, Any]:
    old, core = modules["old"], modules["core"]
    cell = copy.deepcopy(old.build_cell(modules, mechanism, role, target_type, variant))
    instance = cell["instance"]
    target_uav, support_uav = cell["mechanism_uav_id"], cell["objective_uav_id"]
    support_type = other_type(target_type)
    _add_support_suffix(modules, cell, target_type)
    _add_dominated_target_route(modules, cell)
    _add_mechanism_semantic_freedom(modules, cell, role, target_type, variant)
    target_first = _mission_sequence(instance, target_uav)[0]
    support_seq = _mission_sequence(instance, support_uav)
    support_corridor_ids = {cid for mission in support_seq for path in mission["path_options"] for cid in path["corridor_ids"]}
    old_baseline = {row["mission_id"]: copy.deepcopy(row) for row in cell["baseline"]["decisions"]}

    # A fixed connector precedes the objective gadget.  It collides with the
    # target mechanism chain in every repair, so coupling cannot manufacture a
    # gap merely by deleting the low-objective repair.
    offset = 3
    old_origin = support_seq[0]["origin_vertiport"]
    shared_origin, shared_destination = target_first["origin_vertiport"], target_first["destination_vertiport"]
    node_map = {old_origin: shared_destination}
    for mission in support_seq:
        mission["sequence_index"] = int(mission["sequence_index"]) + 1
        mission["origin_vertiport"] = node_map.get(mission["origin_vertiport"], mission["origin_vertiport"])
        mission["destination_vertiport"] = node_map.get(mission["destination_vertiport"], mission["destination_vertiport"])
        mission["expected_incoming_origin_vertiport"] = mission["origin_vertiport"]
        mission["release_slot"] = int(mission["release_slot"]) + offset
        mission["due_slot"] = int(mission["due_slot"]) + offset
    for decision in old_baseline.values():
        if decision["uav_id"] == support_uav:
            decision["depart_slot"] = int(decision["depart_slot"]) + offset
    if "_support_suffix_baseline" in cell:
        cell["_support_suffix_baseline"]["depart_slot"] += offset

    for corridor in instance["topology"]["corridors"]:
        if corridor["corridor_id"] in support_corridor_ids:
            corridor["from_vertiport"] = node_map.get(corridor["from_vertiport"], corridor["from_vertiport"])
            corridor["to_vertiport"] = node_map.get(corridor["to_vertiport"], corridor["to_vertiport"])
    intervention = copy.deepcopy(cell["intervention"])
    for row in intervention.get("closed_corridor_slots", []):
        if row["corridor_id"] in support_corridor_ids:
            row["slot"] = int(row["slot"]) + offset

    connector_id = old.opaque("M", cell["cell_key"] + "|connector", 93)
    connector_corridor_id = old.opaque("C", cell["cell_key"] + "|connector", 93)
    connector_corridor, connector_path = old.corridor_for_slots(
        core, instance["scenario_id"], connector_corridor_id,
        shared_origin, shared_destination, 2, 1.05 + 0.03 * (variant % 3), support_type,
    )
    connector = old.make_mission(connector_id, support_uav, 0, shared_origin, shared_destination, [(connector_corridor, connector_path)], 0, max(6, int(instance["horizon_slots"]) - 2))
    instance["missions"].append(connector)
    instance["topology"]["corridors"].append(connector_corridor)

    support_fleet = next(row for row in instance["fleet"] if row["uav_id"] == support_uav)
    support_fleet.clear()
    support_fleet.update(old.make_fleet_row(core, support_uav, support_type, shared_origin, core.UAV_TYPES[support_type]["reserve_kwh"] + 8.0))
    corridor_index = {row["corridor_id"]: i for i, row in enumerate(instance["topology"]["corridors"])}
    for mission in support_seq:
        rebuilt_paths = []
        for path in mission["path_options"]:
            if len(path["corridor_ids"]) != 1:
                raise RuntimeError("SUPPORT_PATH_NOT_SINGLE_CORRIDOR")
            cid = path["corridor_ids"][0]
            source = instance["topology"]["corridors"][corridor_index[cid]]
            corridor, rebuilt = old.corridor_for_slots(core, instance["scenario_id"], cid, mission["origin_vertiport"], mission["destination_vertiport"], int(path["travel_slots"]), float(source["distance_km"]), support_type, float(mission["payload_kg"]))
            instance["topology"]["corridors"][corridor_index[cid]] = corridor
            rebuilt_paths.append(rebuilt)
        mission["path_options"] = rebuilt_paths
        mission["preferred_construction_path_id"] = rebuilt_paths[0]["path_id"]

    objective_first = support_seq[0]
    objective_first["priority"] = "urgent" if role == "L4_WEIGHTED_TARDINESS_PREFIX_CONTROL" else "routine"
    if role != "L4_WEIGHTED_TARDINESS_PREFIX_CONTROL":
        objective_first["due_slot"] = max(objective_first["due_slot"], 20 + offset)
    connector_energy = float(connector_path["energy_kwh"])
    if role == "L5_DELAY_CHARGE_WAIT_PREFIX_CONTROL":
        slow_high, fast_low = objective_first["path_options"][1], objective_first["path_options"][2]
        suffix = support_seq[1]["path_options"][0]
        charge = float(core.UAV_TYPES[support_type]["charge_kwh_per_block"])
        lower = max(fast_low["energy_kwh"] + suffix["energy_kwh"] + 0.05, slow_high["energy_kwh"] + suffix["energy_kwh"] - charge + 0.05)
        upper = slow_high["energy_kwh"] + suffix["energy_kwh"] - 0.05
        if not lower < upper:
            raise RuntimeError("MIXED_L5_SOC_INTERVAL_EMPTY")
        fraction = (0.35, 0.5, 0.65)[variant % 3]
        support_fleet["initial_soc_kwh"] = round(core.UAV_TYPES[support_type]["reserve_kwh"] + connector_energy + lower + fraction * (upper - lower), 6)
    else:
        support_fleet["initial_soc_kwh"] = round(float(support_fleet["initial_soc_kwh"]) + connector_energy, 6)

    # Corridor topology shares the exact route resource; pad topologies retain
    # a distinct connector route but share origin or destination facilities.
    linked_mission_ids = [target_first["mission_id"], connector_id]
    if topology == TOPOLOGIES[2]:
        baseline_target_path = next(row["path_id"] for row in cell["baseline"]["decisions"] if row["mission_id"] == target_first["mission_id"])
        route_candidates = [p for p in target_first["path_options"] if p["path_id"] != baseline_target_path]
        if mechanism != old.MECHANISMS[0] and route_candidates:
            shared_path = route_candidates[1] if role == "L6_ENERGY_PREFIX_CONTROL" and len(route_candidates) >= 3 else route_candidates[0]
        else:
            shared_path = target_first["path_options"][0]
        shared_corridor = shared_path["corridor_ids"][0]
        connector_path["corridor_ids"] = [shared_corridor]
        connector_path["edge_segments"] = [{**connector_path["edge_segments"][0], "corridor_id": shared_corridor}]
        connector_path["node_sequence"] = [shared_origin, shared_destination]
        connector["path_options"][0] = _refresh_path(core, instance, connector, connector_path)
        connector["preferred_construction_path_id"] = connector["path_options"][0]["path_id"]
        resource = {"kind": "corridor", "node": shared_corridor, "slot": 0, "capacity": 1}
    elif topology == TOPOLOGIES[1]:
        resource = {"kind": "pad", "node": shared_destination, "slot": 2, "capacity": 1}
    else:
        resource = {"kind": "pad", "node": shared_origin, "slot": 0, "capacity": 1}

    nodes = sorted({c["from_vertiport"] for c in instance["topology"]["corridors"]} | {c["to_vertiport"] for c in instance["topology"]["corridors"]})
    instance["topology"]["vertiports"] = [{"vertiport_id": node, "pad_capacity": 2, "charger_count": 2} for node in nodes]
    instance["resources"] = {
        "corridor_capacity_by_slot_default": {row["corridor_id"]: 2 for row in instance["topology"]["corridors"]},
        "pad_capacity_by_slot_default": {node: 2 for node in nodes},
        "charger_capacity_by_slot_default": {node: 2 for node in nodes},
    }
    instance["topology_motif"] = "mixed_fleet_connector_coupled_certificate_bridge"
    instance["provenance"].update({"generator_version": VERSION, "coupling_topology_hidden_private": topology, "mixed_fleet": True, "connector_precedes_objective_chain": True})

    baseline_decisions = []
    connector_baseline = {"mission_id": connector_id, "uav_id": support_uav, "held": False, "path_id": connector["path_options"][0]["path_id"], "depart_slot": 0, "charge_blocks": 0}
    for mission in sorted(instance["missions"], key=lambda row: (row["uav_id"], row["sequence_index"])):
        if mission["mission_id"] == connector_id:
            baseline_decisions.append(connector_baseline)
        elif mission["mission_id"] in old_baseline:
            baseline_decisions.append(copy.deepcopy(old_baseline[mission["mission_id"]]))
        else:
            baseline_decisions.append(copy.deepcopy(cell["_support_suffix_baseline"]))

    private_id = "coupled_v3_" + hashlib.sha256(f"v3|{mechanism}|{role}|{target_type}|{variant}|{topology}".encode()).hexdigest()[:20]
    instance["instance_id"] = private_id
    instance["structural_signatures"] = core.structural_signatures(instance)
    instance.pop("instance_sha256", None)
    instance["instance_sha256"] = core.sha256_obj(instance)
    empty = core.empty_intervention(instance); empty["intervention_sha256"] = core.sha256_obj(empty)
    baseline = core.make_plan(instance, empty, "coupled_connector_preintervention_baseline", baseline_decisions)
    intervention["instance_id"] = private_id
    intervention["baseline_plan_sha256"] = baseline["plan_sha256"]
    intervention["pad_capacity_overrides"] = []
    intervention["charger_capacity_overrides"] = []
    intervention["corridor_capacity_overrides"] = list(intervention.get("corridor_capacity_overrides", []))
    intervention["operations"] = [row for row in intervention.get("operations", []) if row.get("type") != "mixed_fleet_coupling_capacity"]
    cell["coupling_topology"] = topology
    _force_fixed_departure_availability(modules, cell, intervention)
    _rebalance_mechanism_soc_for_semantic_routes(modules, cell, intervention)
    intervention.pop("intervention_sha256", None)
    intervention["intervention_sha256"] = core.sha256_obj(intervention)
    cell.update({"instance": instance, "baseline": baseline, "intervention": intervention, "support_uav_id": support_uav, "support_uav_type": support_type, "connector_mission_id": connector_id, "objective_mission_id": objective_first["mission_id"], "linked_mission_ids": linked_mission_ids, "coupling_resource": resource, "coupling_topology": topology, "private_cell_id": private_id, "_mechanism_labels": tuple(old.MECHANISMS)})
    _balance_public_nuisance_fields(cell, role)
    # The nuisance rebalance changes instance bytes but not the frozen model.
    instance["structural_signatures"] = core.structural_signatures(instance)
    instance.pop("instance_sha256", None)
    instance["instance_sha256"] = core.sha256_obj(instance)
    empty = core.empty_intervention(instance); empty["intervention_sha256"] = core.sha256_obj(empty)
    baseline = core.make_plan(instance, empty, "coupled_connector_preintervention_baseline", baseline_decisions)
    intervention["instance_id"] = private_id
    intervention["baseline_plan_sha256"] = baseline["plan_sha256"]
    intervention.pop("intervention_sha256", None)
    intervention["intervention_sha256"] = core.sha256_obj(intervention)
    cell["baseline"] = baseline
    cell["intervention"] = intervention
    return cell


def decisions_from_solution(core: Any, instance: dict[str, Any], built: dict[str, Any], x: Any) -> list[dict[str, Any]]:
    decisions = []
    for mission in instance["missions"]:
        hold = built["hold_idx"][mission["mission_id"]]
        if x[hold] > 0.5:
            decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0})
        else:
            chosen = [index for index in built["option_indices"][mission["mission_id"]] if x[index] > 0.5]
            if len(chosen) != 1:
                raise RuntimeError("OPTION_EXTRACTION_FAILURE:" + mission["mission_id"])
            option = built["var_meta"][chosen[0]]
            decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": False, "path_id": option["path_id"], "depart_slot": option["depart_slot"], "charge_blocks": option["charge_blocks"]})
    return decisions


def add_row(core: Any, A: Any, lb: Any, ub: Any, coeff: dict[int, float], lower: float, upper: float) -> tuple[Any, Any, Any]:
    vector = core.np.zeros(A.shape[1])
    for index, value in coeff.items():
        vector[index] = value
    return (
        core.vstack([A, core.csr_matrix(vector.reshape(1, -1))], format="csr"),
        core.np.append(lb, lower), core.np.append(ub, upper),
    )


def mechanism_action_evidence(modules: dict[str, Any], cell: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    prod = modules["prod_mechanism"]
    evidence = prod._action_evidence(modules["core"], cell["instance"], cell["intervention"], cell["baseline"], decisions, cell["pair"])
    mechanism = cell["mechanism"]
    route = int(evidence["target_uav_route_change_count"])
    depart = int(evidence["target_uav_departure_change_count"])
    charge = int(evidence["signed_pre_target_charge_block_delta"])
    common = bool(evidence["all_served"] and charge >= 1 and float(evidence["minimum_soc_margin_kwh"]) >= -1e-9)
    if mechanism == modules["old"].MECHANISMS[0]:
        passed = common and route == 0
    elif mechanism == modules["old"].MECHANISMS[1]:
        passed = common and route >= 1
    elif mechanism == modules["old"].MECHANISMS[2]:
        passed = common and route >= 1 and evidence["designated_route_target_changed"] is True and depart == 0
    else:
        passed = common and route >= 1 and evidence["designated_route_target_changed"] is True and depart >= 1
    return {**evidence, "classification": "TRUE" if passed else "FALSE", "selected_mechanism": mechanism if passed else None}


def add_mechanism_constraints(modules: dict[str, Any], cell: dict[str, Any], built: dict[str, Any], A: Any, lb: Any, ub: Any) -> tuple[Any, Any, Any]:
    core, old = modules["core"], modules["old"]
    baseline = {row["mission_id"]: row for row in cell["baseline"]["decisions"]}
    missions = {row["mission_id"]: row for row in cell["instance"]["missions"]}
    soc = cell["pair"]["soc"]
    target = missions[soc["soc_target_mission_id"]]
    predecessors = [m for m in missions.values() if m["uav_id"] == soc["uav_id"] and m["sequence_index"] < target["sequence_index"]]
    coeff = {}
    base_charge = 0
    for mission in predecessors:
        base_charge += int(baseline[mission["mission_id"]]["charge_blocks"])
        for index in built["option_indices"][mission["mission_id"]]:
            coeff[index] = float(built["var_meta"][index]["charge_blocks"])
    A, lb, ub = add_row(core, A, lb, ub, coeff, base_charge + 1, core.np.inf)
    target_missions = [m for m in missions.values() if m["uav_id"] == soc["uav_id"]]
    route_coeff, depart_coeff = {}, {}
    for mission in target_missions:
        base = baseline[mission["mission_id"]]
        for index in built["option_indices"][mission["mission_id"]]:
            meta = built["var_meta"][index]
            route_coeff[index] = float(meta["path_id"] != base["path_id"])
            depart_coeff[index] = float(meta["depart_slot"] != base["depart_slot"])
    mechanism = cell["mechanism"]
    if mechanism == old.MECHANISMS[0]:
        A, lb, ub = add_row(core, A, lb, ub, route_coeff, 0, 0)
    else:
        A, lb, ub = add_row(core, A, lb, ub, route_coeff, 1, core.np.inf)
    if mechanism in {old.MECHANISMS[2], old.MECHANISMS[3]}:
        route_mid = cell["pair"]["route"]["mission_id"]
        base_path = baseline[route_mid]["path_id"]
        designated = {index: float(built["var_meta"][index]["path_id"] != base_path) for index in built["option_indices"][route_mid]}
        A, lb, ub = add_row(core, A, lb, ub, designated, 1, core.np.inf)
        A, lb, ub = add_row(core, A, lb, ub, depart_coeff, 0 if mechanism == old.MECHANISMS[2] else 1, 0 if mechanism == old.MECHANISMS[2] else core.np.inf)
    return A, lb, ub


def _path_corridor_signature(instance: dict[str, Any], mission_id: str, path_id: str | None) -> tuple[str, ...] | None:
    if path_id is None:
        return None
    mission = next(m for m in instance["missions"] if m["mission_id"] == mission_id)
    path = next(p for p in mission["path_options"] if p["path_id"] == path_id)
    return tuple(path["corridor_ids"])


def _decision_semantic_state(instance: dict[str, Any], decision: dict[str, Any]) -> tuple[Any, ...]:
    if decision.get("held"):
        return ("HELD",)
    mission = next(m for m in instance["missions"] if m["mission_id"] == decision["mission_id"])
    blocks = int(decision["charge_blocks"])
    return (
        "SERVED",
        _path_corridor_signature(instance, decision["mission_id"], decision["path_id"]),
        int(decision["depart_slot"]),
        mission["destination_vertiport"] if blocks > 0 else None,
        blocks > 0,
        blocks,
    )


def semantic_decision_signature(core: Any, cell: dict[str, Any], plan: dict[str, Any], intervention: dict[str, Any] | None = None) -> dict[str, Any]:
    instance = cell["instance"]
    signature_cell = cell
    if intervention is not None and intervention is not cell["intervention"]:
        signature_cell = {**cell, "intervention": intervention}
    by_id = {row["mission_id"]: row for row in plan["decisions"]}
    mission_states = []
    for mission in sorted(instance["missions"], key=lambda m: (m["uav_id"], m["sequence_index"], m["mission_id"])):
        state = _decision_semantic_state(instance, by_id[mission["mission_id"]])
        mission_states.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "state": state})
    linked = []
    for mission_id in cell["linked_mission_ids"]:
        keys = sorted(resource_keys_for_decision(core, signature_cell, plan, mission_id), key=lambda x: (x[1], x[0]))
        linked.append({"mission_id": mission_id, "slots": [int(slot) for _, slot in keys]})
    order = [row["mission_id"] for row in sorted(linked, key=lambda row: (min(row["slots"]) if row["slots"] else 10**9, row["mission_id"]))]
    mechanism_states = [row for row in mission_states if row["uav_id"] == cell["mechanism_uav_id"]]
    payload = {
        "mission_states": mission_states,
        "shared_resource_use_order": order,
        "target_mechanism_discrete_action_tuple": mechanism_states,
    }
    return {**payload, "sha256": sha_obj(payload)}


def _semantic_equivalent_indices(instance: dict[str, Any], built: dict[str, Any], decision: dict[str, Any]) -> list[int]:
    mission_id = decision["mission_id"]
    target_state = _decision_semantic_state(instance, decision)
    if decision.get("held"):
        return [built["hold_idx"][mission_id]]
    values = []
    for index in built["option_indices"][mission_id]:
        meta = built["var_meta"][index]
        candidate = {
            "mission_id": mission_id,
            "held": False,
            "path_id": meta["path_id"],
            "depart_slot": meta["depart_slot"],
            "charge_blocks": meta["charge_blocks"],
        }
        if _decision_semantic_state(instance, candidate) == target_state:
            values.append(index)
    if not values:
        raise RuntimeError("TARGET_SEMANTIC_STATE_NOT_IN_MODEL:" + mission_id)
    return values


def _semantic_route_equivalent_indices(instance: dict[str, Any], built: dict[str, Any], decision: dict[str, Any]) -> list[int]:
    if decision.get("held"):
        return [built["hold_idx"][decision["mission_id"]]]
    route = _path_corridor_signature(instance, decision["mission_id"], decision["path_id"])
    return [
        index for index in built["option_indices"][decision["mission_id"]]
        if _path_corridor_signature(instance, decision["mission_id"], built["var_meta"][index]["path_id"]) == route
    ]


def semantic_distinction_mission(cell: dict[str, Any]) -> str:
    labels = cell["_mechanism_labels"]
    support_linked_roles = {
        (label, "L5_DELAY_CHARGE_WAIT_PREFIX_CONTROL") for label in labels
    } | {
        (labels[3], "L4_WEIGHTED_TARDINESS_PREFIX_CONTROL"),
    }
    if cell["mechanism"] == labels[0] or (cell["mechanism"], cell["objective_role"]) in support_linked_roles:
        mission_id = cell.get("objective_mission_id")
        if not mission_id:
            raise RuntimeError("FIXED_ROUTE_SUPPORT_DISTINCTION_MISSION_MISSING")
        return mission_id
    return _mission_sequence(cell["instance"], cell["mechanism_uav_id"])[0]["mission_id"]


def solve_target_alternative(modules: dict[str, Any], cell: dict[str, Any], intervention: dict[str, Any], time_limit: float) -> dict[str, Any]:
    core, formal = modules["core"], modules["formal"]
    instance, baseline = cell["instance"], cell["baseline"]
    target = core.solve_sequential(instance, intervention, baseline, time_limit=time_limit, check_alternative=True)
    if target.get("status") != "OPTIMAL":
        raise RuntimeError("TARGET_NOT_OPTIMAL:" + str(target.get("solver_message")))
    built = core.build_model(instance, intervention, baseline)
    if tuple(name for name, _ in built["tiers"]) != TIERS:
        raise RuntimeError("OBJECTIVE_TIER_DRIFT")
    target_values = {row["name"]: float(row["value"]) for row in target["objective_vector"]}
    target_index = cell["target_layer_index"] - 1
    A, lb, ub = built["A"], built["lb"], built["ub"]
    for name, vector in built["tiers"][:target_index]:
        tolerance = 1e-4 if name == "energy_kwh" else 1e-7
        A = core.vstack([A, core.csr_matrix(vector.reshape(1, -1))], format="csr")
        lb = core.np.append(lb, target_values[name] - tolerance)
        ub = core.np.append(ub, target_values[name] + tolerance)
    A, lb, ub = add_mechanism_constraints(modules, cell, built, A, lb, ub)
    target_map = {row["mission_id"]: row for row in target["decisions"]}
    distinction_mission_id = semantic_distinction_mission(cell)
    selected = {
        index: 1.0 for index in _semantic_route_equivalent_indices(
            instance, built, target_map[distinction_mission_id]
        )
    }
    # The competitor must use a different corridor sequence on the declared
    # mechanism-linked mission.  Departure-only perturbations and duplicate
    # path identifiers cannot satisfy this distinction.
    A, lb, ub = add_row(core, A, lb, ub, selected, 0.0, 0.0)
    target_name, target_vector = built["tiers"][target_index]
    result = core.milp(
        target_vector,
        integrality=core.np.ones(len(built["var_meta"])),
        bounds=core.Bounds(
            core.np.zeros(len(built["var_meta"])),
            core.np.ones(len(built["var_meta"])),
        ),
        constraints=core.LinearConstraint(A, lb, ub),
        options={"time_limit": time_limit, "mip_rel_gap": 0.0, "presolve": True},
    )
    if not (result.success and result.status == 0):
        raise RuntimeError("MECHANISM_PRESERVING_ALTERNATIVE_NOT_FOUND:" + str(result.message))
    alternative_decisions = decisions_from_solution(core, instance, built, result.x)
    alternative = core.make_plan(instance, intervention, "best_mechanism_preserving_equal_prefix_alternative", alternative_decisions)
    target_check = formal.validate_plan(instance, intervention, target, baseline=baseline, oracle=target)
    alternative_check = formal.validate_plan(instance, intervention, alternative, baseline=baseline, oracle=target)
    alt_obj = alternative_check.get("objective") or {}
    prefix_equal = all(abs(float(alt_obj[name]) - target_values[name]) <= (1e-4 if name == "energy_kwh" else 1e-7) for name in TIERS[:target_index])
    gap = float(alt_obj[target_name]) - target_values[target_name]
    difference = []
    alt_map = {row["mission_id"]: row for row in alternative_decisions}
    for mission_id in target_map:
        changed = {key: [target_map[mission_id].get(key), alt_map[mission_id].get(key)] for key in ("path_id", "depart_slot", "charge_blocks", "held") if target_map[mission_id].get(key) != alt_map[mission_id].get(key)}
        if changed:
            difference.append({"mission_id": mission_id, "uav_id": target_map[mission_id]["uav_id"], "changes": changed})
    target_signature = semantic_decision_signature(core, cell, target, intervention)
    alternative_signature = semantic_decision_signature(core, cell, alternative, intervention)
    semantic_distinction = target_signature["sha256"] != alternative_signature["sha256"]
    mechanism_linked_difference = bool(
        semantic_distinction
        and (
            target_signature["target_mechanism_discrete_action_tuple"]
            != alternative_signature["target_mechanism_discrete_action_tuple"]
            or target_signature["shared_resource_use_order"]
            != alternative_signature["shared_resource_use_order"]
            or bool(difference)
        )
    )
    return {
        "target_plan": target, "alternative_plan": alternative,
        "target_objective": target_values, "alternative_objective": alt_obj,
        "target_formal_valid": target_check.get("valid") is True,
        "alternative_formal_valid": alternative_check.get("valid") is True,
        "prefix_equal": prefix_equal, "target_layer_name": target_name, "target_layer_gap": gap,
        "meaningful_gap_floor": cell["meaningful_gap_floor"], "meaningful_positive_gap": gap >= cell["meaningful_gap_floor"],
        "difference_set": difference,
        "target_semantic_signature": target_signature,
        "alternative_semantic_signature": alternative_signature,
        "semantic_distinction": semantic_distinction,
        "semantic_distinction_mission_id": distinction_mission_id,
        "mechanism_linked_difference": mechanism_linked_difference,
        "target_mechanism_action": mechanism_action_evidence(modules, cell, target["decisions"]),
        "alternative_mechanism_action": mechanism_action_evidence(modules, cell, alternative_decisions),
        "solver_status": int(result.status), "solver_message": str(result.message),
    }


def resource_keys_for_decision(core: Any, cell: dict[str, Any], plan: dict[str, Any], mission_id: str) -> set[tuple[str, int]]:
    instance, intervention = cell["instance"], cell["intervention"]
    activity = core.plan_activity(instance, plan, intervention)
    decision = next(row for row in plan["decisions"] if row["mission_id"] == mission_id)
    mission = next(row for row in instance["missions"] if row["mission_id"] == mission_id)
    built = core.build_model(instance, intervention, cell["baseline"])
    option = next(built["var_meta"][i] for i in built["option_indices"][mission_id] if built["var_meta"][i]["path_id"] == decision["path_id"] and built["var_meta"][i]["depart_slot"] == decision["depart_slot"] and built["var_meta"][i]["charge_blocks"] == decision["charge_blocks"])
    kind, node = cell["coupling_resource"]["kind"], cell["coupling_resource"]["node"]
    if kind == "pad":
        return {(mission["origin_vertiport"], option["depart_slot"]), (mission["destination_vertiport"], option["arrival_slot"])} & {(node, slot) for slot in range(instance["horizon_slots"])}
    if kind == "charger":
        return {(mission["destination_vertiport"], slot) for slot in range(option["charge_start_slot"], option["charge_start_slot"] + option["charge_blocks"])} & {(node, slot) for slot in range(instance["horizon_slots"])}
    return set(option["service_occupancy"]) & {(node, slot) for slot in range(instance["horizon_slots"])}


def coupling_trace(modules: dict[str, Any], cell: dict[str, Any], pair: dict[str, Any]) -> dict[str, Any]:
    core = modules["core"]
    plans = {"target": pair["target_plan"], "alternative": pair["alternative_plan"]}
    rows = []
    all_active = False
    for plan_name, plan in plans.items():
        keys = {mission_id: sorted(resource_keys_for_decision(core, cell, plan, mission_id)) for mission_id in cell["linked_mission_ids"]}
        activity = core.plan_activity(cell["instance"], plan, cell["intervention"])
        counter = activity[cell["coupling_resource"]["kind"]]
        resource_key = (cell["coupling_resource"]["node"], int(cell["coupling_resource"]["slot"]))
        binding = [list(resource_key)] if counter.get(resource_key, 0) == int(cell["coupling_resource"]["capacity"]) else []
        all_active = all_active or bool(binding)
        rows.append({"plan": plan_name, "linked_mission_resource_keys": keys, "binding_keys": binding})
    built = core.build_model(cell["instance"], cell["intervention"], cell["baseline"])
    feasible_keys = {}
    for mission_id in cell["linked_mission_ids"]:
        keys = set()
        mission = next(row for row in cell["instance"]["missions"] if row["mission_id"] == mission_id)
        kind, node = cell["coupling_resource"]["kind"], cell["coupling_resource"]["node"]
        for index in built["option_indices"][mission_id]:
            meta = built["var_meta"][index]
            if kind == "pad":
                keys.update({(mission["origin_vertiport"], meta["depart_slot"]), (mission["destination_vertiport"], meta["arrival_slot"])})
            elif kind == "charger":
                keys.update((mission["destination_vertiport"], slot) for slot in range(meta["charge_start_slot"], meta["charge_start_slot"] + meta["charge_blocks"]))
            else:
                keys.update(meta["service_occupancy"])
        feasible_keys[mission_id] = {key for key in keys if key[0] == node}
    intersection = set.intersection(*(feasible_keys[mid] for mid in cell["linked_mission_ids"]))
    constrained_key = (cell["coupling_resource"]["node"], int(cell["coupling_resource"]["slot"]))
    return {"topology": cell["coupling_topology"], "resource": cell["coupling_resource"], "constraint_incidence_connected": constrained_key in intersection, "potential_collision_keys": [list(key) for key in sorted(intersection)], "binding_trace_present": all_active, "plans": rows}


def decoupled_intervention(core: Any, cell: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(cell["intervention"])
    if cell["coupling_resource"]["kind"] == "pad":
        value["pad_capacity_overrides"] = [row for row in value.get("pad_capacity_overrides", []) if row["vertiport_id"] != cell["coupling_resource"]["node"]]
    elif cell["coupling_resource"]["kind"] == "charger":
        value["charger_capacity_overrides"] = [row for row in value.get("charger_capacity_overrides", []) if row["vertiport_id"] != cell["coupling_resource"]["node"]]
    else:
        value["corridor_capacity_overrides"] = [row for row in value.get("corridor_capacity_overrides", []) if row["corridor_id"] != cell["coupling_resource"]["node"]]
    value["operations"] = [row for row in value.get("operations", []) if row.get("type") != "mixed_fleet_coupling_capacity"]
    value.pop("intervention_sha256", None)
    value["intervention_sha256"] = core.sha256_obj(value)
    return value


def bind_capacity_at_selected_collision(core: Any, cell: dict[str, Any], uncoupled_pair: dict[str, Any], variant: int) -> None:
    """Bind one deterministic shared-resource collision exposed pre-admission.

    The collision is discovered from the uncoupled target/alternative solves,
    not from a cell label.  The coupled candidate is then solved again from
    scratch and must pass the decoupling counterfactual.
    """
    collisions: set[tuple[str, int]] = set()
    for plan_key in ("target_plan", "alternative_plan"):
        plan = uncoupled_pair[plan_key]
        mission_keys = [resource_keys_for_decision(core, cell, plan, mission_id) for mission_id in cell["linked_mission_ids"]]
        collisions.update(set.intersection(*mission_keys))
    ordered = sorted(collisions, key=lambda key: (key[1], key[0]))
    if not ordered:
        raise RuntimeError("NO_SELECTED_SHARED_RESOURCE_COLLISION")
    node, slot = ordered[variant % len(ordered)]
    resource = cell["coupling_resource"]
    if node != resource["node"]:
        raise RuntimeError("SELECTED_COLLISION_RESOURCE_DRIFT")
    resource["slot"] = int(slot)
    intervention = decoupled_intervention(core, cell)
    if resource["kind"] == "pad":
        intervention["pad_capacity_overrides"] = [{"vertiport_id": node, "slot": int(slot), "capacity": 1}]
    elif resource["kind"] == "charger":
        intervention["charger_capacity_overrides"] = [{"vertiport_id": node, "slot": int(slot), "capacity": 1}]
    else:
        intervention["corridor_capacity_overrides"] = list(intervention.get("corridor_capacity_overrides", [])) + [{"corridor_id": node, "slot": int(slot), "capacity": 1}]
    intervention["operations"] = list(intervention.get("operations", [])) + [{"type": "mixed_fleet_coupling_capacity", "topology": cell["coupling_topology"], "resource": copy.deepcopy(resource)}]
    intervention.pop("intervention_sha256", None)
    intervention["intervention_sha256"] = core.sha256_obj(intervention)
    cell["intervention"] = intervention


def parent_success(modules: dict[str, Any], cell: dict[str, Any], pair: dict[str, Any], time_limit: float) -> dict[str, Any]:
    old = modules["old"]
    adapted = {"target_plan": pair["target_plan"]}
    return old.parent_success(modules, cell, adapted, time_limit)


def solve_decoupled_counterfactual(modules: dict[str, Any], cell: dict[str, Any], coupled_pair: dict[str, Any], time_limit: float) -> dict[str, Any]:
    core = modules["core"]
    intervention = decoupled_intervention(core, cell)
    try:
        pair = solve_target_alternative(modules, cell, intervention, time_limit)
        functional_changes = {
            "target_plan_changed": pair["target_semantic_signature"]["sha256"] != coupled_pair["target_semantic_signature"]["sha256"],
            "competitor_plan_changed": pair["alternative_semantic_signature"]["sha256"] != coupled_pair["alternative_semantic_signature"]["sha256"],
            "shared_resource_order_changed": (
                pair["target_semantic_signature"]["shared_resource_use_order"] != coupled_pair["target_semantic_signature"]["shared_resource_use_order"]
                or pair["alternative_semantic_signature"]["shared_resource_use_order"] != coupled_pair["alternative_semantic_signature"]["shared_resource_use_order"]
            ),
            "competitor_feasibility_changed": False,
        }
        threshold = 0.001 if coupled_pair["target_layer_name"] == "energy_kwh" else 1.0
        gap_mediated = abs(float(pair["target_layer_gap"]) - float(coupled_pair["target_layer_gap"])) >= threshold
        return {"competitor_feasible": True, "pair": pair, "functional_changes": functional_changes, "functional_effect": any(functional_changes.values()) or gap_mediated, "gap_mediated": gap_mediated}
    except RuntimeError as exc:
        if not str(exc).startswith("MECHANISM_PRESERVING_ALTERNATIVE_NOT_FOUND:"):
            raise
        target = core.solve_sequential(cell["instance"], intervention, cell["baseline"], time_limit=time_limit, check_alternative=True)
        if target.get("status") != "OPTIMAL":
            raise RuntimeError("DECOUPLED_TARGET_NOT_OPTIMAL:" + str(target.get("solver_message")))
        target_signature = semantic_decision_signature(core, cell, target, intervention)
        functional_changes = {
            "target_plan_changed": target_signature["sha256"] != coupled_pair["target_semantic_signature"]["sha256"],
            "competitor_plan_changed": False,
            "shared_resource_order_changed": target_signature["shared_resource_use_order"] != coupled_pair["target_semantic_signature"]["shared_resource_use_order"],
            "competitor_feasibility_changed": True,
        }
        return {"competitor_feasible": False, "target_plan": target, "target_semantic_signature": target_signature, "alternative_error": str(exc), "functional_changes": functional_changes, "functional_effect": True, "gap_mediated": False}


def construct_certificate(modules: dict[str, Any], mechanism: str, role: str, target_type: str, variant: int, topology: str, time_limit: float) -> dict[str, Any]:
    started = time.perf_counter()
    cell = build_coupled_cell(modules, mechanism, role, target_type, variant, topology)
    uncoupled_intervention = decoupled_intervention(modules["core"], cell)
    uncoupled_pair = solve_target_alternative(modules, cell, uncoupled_intervention, time_limit)
    bind_capacity_at_selected_collision(modules["core"], cell, uncoupled_pair, variant)
    pair = solve_target_alternative(modules, cell, cell["intervention"], time_limit)
    production = modules["prod_mechanism"].mechanism_certificate(cell["instance"], cell["intervention"], cell["baseline"], cell["pair"], time_limit=time_limit)
    independent = modules["ind_mechanism"].independent_certificate(cell["instance"], cell["intervention"], cell["baseline"], cell["pair"], time_limit=time_limit)
    trace = coupling_trace(modules, cell, pair)
    decoupled = solve_decoupled_counterfactual(modules, cell, pair, time_limit)
    decoupling_effect = bool(decoupled["functional_effect"])
    parent = parent_success(modules, cell, pair, time_limit)
    mechanism_ok = bool(production.get("accepted") is True and independent.get("accepted") is True and production.get("selected_mechanism") == mechanism and independent.get("selected_mechanism") == mechanism)
    plans_mechanism_ok = pair["target_mechanism_action"]["classification"] == "TRUE" and pair["alternative_mechanism_action"]["classification"] == "TRUE"
    mixed = {row["uav_type"] for row in cell["instance"]["fleet"]} == set(TARGET_TYPES)
    both_participate = all(any(d["uav_id"] == u["uav_id"] and not d["held"] for d in pair["target_plan"]["decisions"]) for u in cell["instance"]["fleet"])
    admitted = bool(
        pair["target_formal_valid"] and pair["alternative_formal_valid"] and pair["prefix_equal"] and pair["meaningful_positive_gap"]
        and pair["semantic_distinction"] and pair["mechanism_linked_difference"] and mechanism_ok and plans_mechanism_ok and mixed and both_participate
        and trace["constraint_incidence_connected"] and trace["binding_trace_present"] and decoupling_effect and parent["parent_success"]
    )
    private = {
        "version": VERSION + "_private_certificate", "contract_version": CONTRACT_VERSION,
        "evidence_scope": "DEVELOPMENT_ONLY_NOT_FORMAL_CONFIRMATION",
        "cell": {"cell_id": cell["private_cell_id"], "mechanism": mechanism, "objective_role": role, "target_uav_type": target_type, "support_uav_type": cell["support_uav_type"], "variant": variant, "coupling_topology": topology},
        "instance": cell["instance"], "baseline": cell["baseline"], "intervention": cell["intervention"], "selected_pair": cell["pair"],
        "q2_repair_certificates": [{"role": "TARGET_LEXICOGRAPHIC_OPTIMUM", "plan": pair["target_plan"]}, {"role": "BEST_MECHANISM_PRESERVING_EQUAL_PREFIX_ALTERNATIVE", "plan": pair["alternative_plan"]}],
        "coupled_pair_certificate": pair, "production_mechanism_necessity": production, "independent_mechanism_necessity": independent,
        "coupling_trace": trace, "decoupling_counterfactual": decoupled,
        "parent_success_certificate": parent, "mixed_fleet_participation": {"mixed": mixed, "both_served": both_participate},
        "admitted": admitted, "runtime_sec": round(time.perf_counter() - started, 6),
    }
    private["certificate_sha256"] = sha_obj(private)
    public_instance = copy.deepcopy(cell["instance"])
    public_instance["provenance"].pop("coupling_topology_hidden_private", None)
    public = {"version": VERSION + "_public_projection", "evidence_scope": "DEVELOPMENT_PUBLIC_NOT_FORMAL_POOL", "instance": public_instance, "baseline": copy.deepcopy(cell["baseline"]), "operational_intervention": copy.deepcopy(cell["intervention"])}
    for row in public["operational_intervention"].get("operations", []):
        row.pop("topology", None); row.pop("resource", None)
    public["public_projection_sha256"] = sha_obj(public)
    summary = {
        "cell_id": cell["private_cell_id"], "mechanism": mechanism, "objective_role": role, "target_uav_type": target_type,
        "coupling_topology": topology, "variant": variant, "admitted": admitted, "q2_count": 2,
        "mechanism_necessity": mechanism_ok, "both_plans_mechanism_true": plans_mechanism_ok,
        "prefix_equal": pair["prefix_equal"], "target_layer_name": pair["target_layer_name"], "target_layer_gap": pair["target_layer_gap"],
        "meaningful_positive_gap": pair["meaningful_positive_gap"],
        "formal_pair": pair["target_formal_valid"] and pair["alternative_formal_valid"], "mechanism_linked_difference": pair["mechanism_linked_difference"],
        "constraint_incidence_connected": trace["constraint_incidence_connected"], "binding_trace": trace["binding_trace_present"],
        "semantic_distinction": pair["semantic_distinction"], "decoupling_effect": decoupling_effect, "gap_mediated": decoupled["gap_mediated"], "mixed_fleet": mixed and both_participate, "v4": parent["binding_v4"]["activation_pass"], "parent_success": parent["parent_success"], "runtime_sec": private["runtime_sec"],
        "certificate_sha256": private["certificate_sha256"], "public_projection_sha256": public["public_projection_sha256"],
    }
    return {"summary": summary, "private": private, "public": public}


def write_result(output: Path, result: dict[str, Any]) -> None:
    (output / "private").mkdir(parents=True, exist_ok=True); (output / "public").mkdir(parents=True, exist_ok=True)
    cid = result["summary"]["cell_id"]
    (output / "private" / f"{cid}.json").write_text(json.dumps(result["private"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output / "public" / f"PUB_{cid}.json").write_text(json.dumps(result["public"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _candidate_record(result: dict[str, Any], attempt_number: int) -> dict[str, Any]:
    summary = result["summary"]
    pair = result["private"]["coupled_pair_certificate"]
    trace = result["private"]["coupling_trace"]
    return {
        **summary,
        "attempt_number": attempt_number,
        "candidate_seed": int(hashlib.sha256(summary["cell_id"].encode()).hexdigest()[:12], 16),
        "target_semantic_signature_sha256": pair["target_semantic_signature"]["sha256"],
        "alternative_semantic_signature_sha256": pair["alternative_semantic_signature"]["sha256"],
        "difference_set": pair["difference_set"],
        "target_objective": pair["target_objective"],
        "alternative_objective": pair["alternative_objective"],
        "binding_resource": trace["resource"],
        "decoupling_functional_changes": result["private"]["decoupling_counterfactual"]["functional_changes"],
    }


def select_balanced_matrix(candidates: dict[tuple[str, str], list[dict[str, Any]]], mechanisms: tuple[str, ...], roles: tuple[str, ...], require_all_gap_roles: bool = True) -> list[dict[str, Any]] | None:
    cells = [(mechanism, role) for mechanism in mechanisms for role in roles]
    cells.sort(key=lambda key: (len(candidates.get(key, [])), key))

    def valid_complete(chosen: list[dict[str, Any]]) -> bool:
        if Counter(row["summary"]["target_uav_type"] for row in chosen) != Counter({TARGET_TYPES[0]: 6, TARGET_TYPES[1]: 6}):
            return False
        topologies = {row["summary"]["coupling_topology"] for row in chosen}
        if topologies != set(TOPOLOGIES):
            return False
        for mechanism in mechanisms:
            if len({row["summary"]["coupling_topology"] for row in chosen if row["summary"]["mechanism"] == mechanism}) < 2:
                return False
        for role in roles:
            if len({row["summary"]["coupling_topology"] for row in chosen if row["summary"]["objective_role"] == role}) < 2:
                return False
        mediated = [row["summary"] for row in chosen if row["summary"]["gap_mediated"]]
        if require_all_gap_roles:
            if {row["objective_role"] for row in mediated} != set(roles):
                return False
            if {row["coupling_topology"] for row in mediated} != set(TOPOLOGIES):
                return False
        return True

    def visit(index: int, chosen: list[dict[str, Any]], fixed_count: int) -> list[dict[str, Any]] | None:
        if fixed_count > 6 or fixed_count + (len(cells) - index) < 6:
            return None
        if index == len(cells):
            return list(chosen) if valid_complete(chosen) else None
        for result in sorted(candidates.get(cells[index], []), key=lambda row: (row["attempt_number"], row["summary"]["cell_id"])):
            chosen.append(result)
            found = visit(index + 1, chosen, fixed_count + int(result["summary"]["target_uav_type"] == TARGET_TYPES[0]))
            if found is not None:
                return found
            chosen.pop()
        return None

    return visit(0, [], 0)


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo", required=True); parser.add_argument("--output", required=True); parser.add_argument("--time-limit", type=float, default=20.0); parser.add_argument("--max-variants", type=int, default=12)
    args = parser.parse_args(); repo, output = Path(args.repo).resolve(), Path(args.output).resolve(); modules = load_modules(repo)
    output.mkdir(parents=True, exist_ok=True)
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    attempts: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    attempt_number = 0
    for mechanism in modules["old"].MECHANISMS:
        for role in modules["old"].ROLES:
            for target_type in TARGET_TYPES:
                for topology in TOPOLOGIES:
                    qualified = None
                    bucket_attempts = 0
                    for variant in range(args.max_variants):
                        attempt_number += 1; bucket_attempts += 1
                        base = {"attempt_number": attempt_number, "mechanism": mechanism, "objective_role": role, "target_uav_type": target_type, "variant": variant, "coupling_topology": topology}
                        try:
                            result = construct_certificate(modules, mechanism, role, target_type, variant, topology, args.time_limit)
                            failures = [
                                key for key, value in result["summary"].items()
                                if isinstance(value, bool) and not value and key not in {"admitted", "gap_mediated"}
                            ]
                            pair = result["private"]["coupled_pair_certificate"]
                            attempts.append({
                                **base,
                                "admitted": result["summary"]["admitted"],
                                "failure_predicates": failures,
                                "target_layer_gap": pair["target_layer_gap"],
                                "target_mechanism_action": pair["target_mechanism_action"]["classification"],
                                "alternative_mechanism_action": pair["alternative_mechanism_action"]["classification"],
                                "target_action_counts": {
                                    "route": pair["target_mechanism_action"].get("target_uav_route_change_count"),
                                    "departure": pair["target_mechanism_action"].get("target_uav_departure_change_count"),
                                    "charge_delta": pair["target_mechanism_action"].get("signed_pre_target_charge_block_delta"),
                                },
                                "alternative_action_counts": {
                                    "route": pair["alternative_mechanism_action"].get("target_uav_route_change_count"),
                                    "departure": pair["alternative_mechanism_action"].get("target_uav_departure_change_count"),
                                    "charge_delta": pair["alternative_mechanism_action"].get("signed_pre_target_charge_block_delta"),
                                },
                                "semantic_distinction": pair["semantic_distinction"],
                                "decoupling_effect": result["summary"]["decoupling_effect"],
                                "gap_mediated": result["summary"]["gap_mediated"],
                            })
                            if result["summary"]["admitted"]:
                                result["attempt_number"] = attempt_number
                                candidates[(mechanism, role)].append(result)
                                qualified = _candidate_record(result, attempt_number)
                                break
                        except Exception as exc:
                            attempts.append({**base, "admitted": False, "exception_type": type(exc).__name__, "message": str(exc)})
                    matrix.append({"mechanism": mechanism, "objective_role": role, "target_uav_type": target_type, "coupling_topology": topology, "attempts": bucket_attempts, "qualified": qualified is not None, "candidate": qualified})
    chosen = select_balanced_matrix(candidates, tuple(modules["old"].MECHANISMS), tuple(modules["old"].ROLES), require_all_gap_roles=True)
    strong_gap_mediation_complete = chosen is not None
    if chosen is None:
        # Preserve a complete mandatory-functional bridge for analysis without
        # misreporting the stronger gap-mediation gate as passed.
        chosen = select_balanced_matrix(candidates, tuple(modules["old"].MECHANISMS), tuple(modules["old"].ROLES), require_all_gap_roles=False)
    selected_results = chosen or []
    rows = []
    for result in selected_results:
        write_result(output, result)
        rows.append(result["summary"])
    failure_taxonomy = Counter()
    for row in attempts:
        if row["admitted"]:
            continue
        if row.get("exception_type"):
            failure_taxonomy[str(row.get("message", "")).split(":", 1)[0]] += 1
        elif row.get("failure_predicates"):
            failure_taxonomy[row["failure_predicates"][0]] += 1
        else:
            failure_taxonomy["UNCLASSIFIED_REJECTION"] += 1
    pool = {"version": VERSION + "_candidate_pool", "matrix": matrix, "qualified_candidate_count": sum(len(v) for v in candidates.values()), "attempt_count": len(attempts), "failure_taxonomy": dict(failure_taxonomy), "attempts": attempts}
    pool["sha256"] = sha_obj(pool)
    (output / "CANDIDATE_FEASIBILITY_MATRIX.json").write_text(json.dumps(pool, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    summary = {"version": VERSION + "_summary", "evidence_scope": "DEVELOPMENT_ONLY", "cell_count": 12, "admitted_count": len(rows), "mandatory_functional_gate_complete": len(rows) == 12, "strong_gap_mediation_gate_complete": strong_gap_mediation_complete, "candidate_attempt_count": len(attempts), "qualified_candidate_count": sum(len(v) for v in candidates.values()), "production_subsolve_count": int(modules["solve_counter"]["subsolves"]), "rows": rows, "target_uav_counts": dict(Counter(row["target_uav_type"] for row in rows)), "topology_counts": dict(Counter(row["coupling_topology"] for row in rows)), "gap_mediation_role_coverage": sorted({row["objective_role"] for row in rows if row["gap_mediated"]}), "gap_mediation_topology_coverage": sorted({row["coupling_topology"] for row in rows if row["gap_mediated"]}), "failure_taxonomy": dict(failure_taxonomy), "formal_confirmation_count": 0, "formal_pool_count": 0, "model_api_network_call_count": 0, "secret_or_dotenv_read_count": 0}
    summary["summary_sha256"] = sha_obj(summary); output.mkdir(parents=True, exist_ok=True); (output / "BRIDGE_PILOT_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"admitted": len(rows), "attempts": len(attempts), "qualified": summary["qualified_candidate_count"], "strong_gap_mediation_complete": strong_gap_mediation_complete, "topologies": summary["topology_counts"]}, sort_keys=True)); return 0 if len(rows) == 12 else 2


if __name__ == "__main__":
    raise SystemExit(main())
