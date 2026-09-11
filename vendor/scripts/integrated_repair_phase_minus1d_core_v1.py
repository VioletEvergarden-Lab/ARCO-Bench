#!/usr/bin/env python3
"""Shared analysis-only compiler and MILP kernel for Phase -1C-R.

The module never reads or writes frozen v2 artifacts. It operates only on a
caller-supplied preview namespace and marks every artifact as non-release.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack


FLAGS = ["ANALYSIS_ONLY", "PREVIEW_NOT_RELEASE", "NOT_A_BENCHMARK_REFERENCE", "NO_MODEL_API"]
CORE_VERSION = "integrated_repair_phase_minus1d_core_v1"
INSTANCE_VERSION = "integrated_repair_phase_minus1d_instance_v1"
MODEL_VERSION = "integrated_repair_phase_minus1d_calibration_milp_v1"
COMPILER_VERSION = "integrated_repair_phase_minus1d_intervention_compiler_v1"
SLOT_MIN = 5
TURNAROUND_SLOTS = 1
MAX_CHARGE_BLOCKS = 3

UAV_TYPES = {
    "multirotor_cargo_uav": {
        "unmanned": True, "travel_time_coefficient": 1.00,
        "payload_capacity_kg": 4.0, "battery_capacity_kwh": 16.0, "reserve_kwh": 1.5,
        "empty_energy_kwh_per_km": 0.100, "payload_energy_kwh_per_km_kg": 0.026,
        "wind_energy_multiplier_per_level": 0.11, "charge_kwh_per_block": 1.20,
        "max_wind_level": 1, "compatible_layers": ["L120_220", "L220_320"],
    },
    "fixed_wing_vtol_cargo_uav": {
        "unmanned": True, "travel_time_coefficient": 0.86,
        "payload_capacity_kg": 7.0, "battery_capacity_kwh": 22.0, "reserve_kwh": 2.5,
        "empty_energy_kwh_per_km": 0.145, "payload_energy_kwh_per_km_kg": 0.012,
        "wind_energy_multiplier_per_level": 0.065, "charge_kwh_per_block": 0.95,
        "max_wind_level": 2, "compatible_layers": ["L120_220", "L220_320"],
    },
}


def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj):
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stable_level(*parts, mod=3):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) % mod


def select_parent_entries(parent_manifest):
    entries = parent_manifest["entries"]
    selected = []
    grouped = defaultdict(list)
    for e in entries:
        if e["ood_axis"] == "id":
            grouped[(e["family"], e["difficulty"])].append(e)
    regimes = ["no_op", "binding", "overcritical"]
    for key in sorted(grouped):
        group = sorted(grouped[key], key=lambda e: (e["split"], e["seed"], e["scenario_id"]))
        if len(group) < 3:
            raise ValueError(f"insufficient ID parents for {key}: {len(group)}")
        for regime, entry in zip(regimes, group[:3]):
            selected.append((entry, regime, "id_calibration"))
    composed = sorted((e for e in entries if e["family"] == "composed_resource_repair"), key=lambda e: (e["difficulty"], e["seed"]))
    by_diff = defaultdict(list)
    for e in composed:
        by_diff[e["difficulty"]].append(e)
    for diff in ("easy", "medium", "hard"):
        if len(by_diff[diff]) != 3:
            raise ValueError(f"composed parent count for {diff}")
        for regime, entry in zip(regimes, by_diff[diff]):
            selected.append((entry, regime, "intervention_composition_ood"))
    topo = sorted((e for e in entries if e["ood_axis"] == "held_out_topology_motif"), key=lambda e: (e["difficulty"], e["seed"]))
    by_diff.clear()
    for e in topo:
        by_diff[e["difficulty"]].append(e)
    for diff in ("easy", "medium", "hard"):
        if len(by_diff[diff]) != 3:
            raise ValueError(f"topology OOD parent count for {diff}")
        for regime, entry in zip(regimes, by_diff[diff]):
            selected.append((entry, regime, "topology_ood"))
    if len(selected) != 63 or len({x[0]["scenario_id"] for x in selected}) != 63:
        raise ValueError("selection must contain 63 unique parents")
    return selected


def path_metrics(path, corridor_by_id, uav_type, payload_kg, scenario_id):
    cfg = UAV_TYPES[uav_type]
    distance = sum(corridor_by_id[c]["distance_km"] for c in path["corridor_ids"])
    base_time = sum(corridor_by_id[c]["base_travel_time_min"] for c in path["corridor_ids"])
    wind_levels = []
    segments = []
    offset = 0
    for pos, cid in enumerate(path["corridor_ids"]):
        c = corridor_by_id[cid]
        wind = stable_level(scenario_id, cid, mod=3)
        if pos == 0:
            wind = min(wind, 1)
        wind_levels.append(wind)
        duration = max(1, math.ceil((c["base_travel_time_min"] * cfg["travel_time_coefficient"] * (1 + 0.06 * wind)) / SLOT_MIN))
        segments.append({"corridor_id": cid, "offset_slot": offset, "duration_slots": duration, "wind_level": wind})
        offset += duration
    max_wind = max(wind_levels, default=0)
    layers = {corridor_by_id[c]["altitude_layer"] for c in path["corridor_ids"]}
    corridor_available = all(
        corridor_by_id[c].get("authorized", True)
        and not corridor_by_id[c].get("weather_closed", False)
        and not corridor_by_id[c].get("no_fly", False)
        for c in path["corridor_ids"]
    )
    endpoint_continuous = bool(path.get("node_sequence")) and len(path["node_sequence"]) == len(path["corridor_ids"]) + 1
    current = path["node_sequence"][0] if endpoint_continuous else None
    for cid in path["corridor_ids"]:
        c = corridor_by_id[cid]
        endpoint_continuous = endpoint_continuous and c["from_vertiport"] == current
        current = c["to_vertiport"]
    endpoint_continuous = endpoint_continuous and current == path["node_sequence"][-1]
    compatible = max_wind <= cfg["max_wind_level"] and layers.issubset(set(cfg["compatible_layers"])) and corridor_available and endpoint_continuous
    energy = distance * (cfg["empty_energy_kwh_per_km"] + payload_kg * cfg["payload_energy_kwh_per_km_kg"])
    energy *= 1 + cfg["wind_energy_multiplier_per_level"] * (sum(wind_levels) / max(1, len(wind_levels)))
    return {
        "path_id": path["path_id"], "corridor_ids": path["corridor_ids"],
        "node_sequence": path["node_sequence"],
        "distance_km": round(distance, 6), "travel_time_min_unrounded": round(base_time * cfg["travel_time_coefficient"], 6),
        "travel_slots": offset, "energy_kwh": round(energy, 6), "edge_segments": segments,
        "max_wind_level": max_wind, "compatible": compatible,
        "compatibility_evidence": {"wind": max_wind <= cfg["max_wind_level"], "layer": layers.issubset(set(cfg["compatible_layers"])), "corridor_available": corridor_available, "endpoint_continuous": endpoint_continuous},
        "energy_provenance": "literature_bounded_synthetic_uav_payload_distance_wind_affine_v2",
    }


def generate_instance(parent_scenario, parent_skeleton, parent_entry, regime, pool_role, generator_hash):
    scenario_id = parent_scenario["scenario_id"].replace("preview_ir", "preview_ir1d")
    paths = {p["path_id"]: p for p in parent_scenario["path_registry"]}
    corridors = copy.deepcopy(parent_scenario["topology"]["corridors"])
    corridor_by_id = {c["corridor_id"]: c for c in corridors}
    vps = copy.deepcopy(parent_scenario["topology"]["vertiports"])
    assignments = sorted(parent_skeleton["assignments"], key=lambda a: (a["vehicle_id"], a["sequence_index"]))
    assignment_by_mission = {a["mission_id"]: a for a in assignments}
    legacy_vehicles = {v["vehicle_id"]: v for v in parent_scenario["vehicles"]}
    fleet = []
    legacy_to_uav = {}
    for i, legacy_id in enumerate(sorted(legacy_vehicles)):
        legacy = legacy_vehicles[legacy_id]
        uav_type = "multirotor_cargo_uav" if legacy["vehicle_type"] == "cargo_uav" else "fixed_wing_vtol_cargo_uav"
        uav_id = f"UAV_{i+1:02d}"
        legacy_to_uav[legacy_id] = uav_id
        fleet.append({
            "uav_id": uav_id, "legacy_vehicle_id": legacy_id, "uav_type": uav_type,
            "unmanned": True, "payload_capacity_kg": UAV_TYPES[uav_type]["payload_capacity_kg"],
            "battery_capacity_kwh": UAV_TYPES[uav_type]["battery_capacity_kwh"],
            "initial_soc_kwh": 0.0, "reserve_kwh": UAV_TYPES[uav_type]["reserve_kwh"],
            "start_vertiport": legacy["start_vertiport"],
            "available_slot": math.floor(legacy["available_time_min"] / SLOT_MIN),
            **UAV_TYPES[uav_type],
        })
    mission_source = {m["mission_id"]: m for m in parent_scenario["missions"]}
    sequence_by_uav = defaultdict(list)
    for a in assignments:
        sequence_by_uav[legacy_to_uav[a["vehicle_id"]]].append(a)
    # Deterministically choose a feasible UAV type before the instance is frozen.
    # No path compatibility bit is ever overridden.
    uav_type_regeneration_count = 0
    for uav_id, seq in sorted(sequence_by_uav.items()):
        uav = next(x for x in fleet if x["uav_id"] == uav_id)
        original_type = uav["uav_type"]
        feasible_types = []
        for candidate_type in sorted(UAV_TYPES):
            cfg = UAV_TYPES[candidate_type]
            ok = True
            for a in seq:
                source = mission_source[a["mission_id"]]
                service = [path_metrics(paths[pid], corridor_by_id, candidate_type, source["payload_kg"], scenario_id) for pid in source["admissible_path_ids"]]
                ok = ok and source["payload_kg"] <= cfg["payload_capacity_kg"] + 1e-9 and any(p["compatible"] for p in service)
                if a["deadhead_path_id"]:
                    dh = path_metrics(paths[a["deadhead_path_id"]], corridor_by_id, candidate_type, 0.0, scenario_id)
                    ok = ok and dh["compatible"]
            if ok:
                feasible_types.append(candidate_type)
        if not feasible_types:
            raise ValueError(f"BASELINE_INVALID_INCOMPATIBLE_UAV_PATH:{uav_id}")
        chosen_type = original_type if original_type in feasible_types else feasible_types[0]
        if chosen_type != original_type:
            uav_type_regeneration_count += 1
        preserved = {k: uav[k] for k in ("uav_id", "legacy_vehicle_id", "start_vertiport", "available_slot", "battery_capacity_kwh", "initial_soc_kwh", "reserve_kwh")}
        uav.clear(); uav.update(preserved); uav.update({"uav_type": chosen_type, **UAV_TYPES[chosen_type]})
        uav["battery_capacity_kwh"] = UAV_TYPES[chosen_type]["battery_capacity_kwh"]
        uav["reserve_kwh"] = UAV_TYPES[chosen_type]["reserve_kwh"]
    uav_by_id = {u["uav_id"]: u for u in fleet}
    compiled_missions = []
    min_energy_by_uav = Counter()
    nominal_clock = {u["uav_id"]: u["available_slot"] for u in fleet}
    for uav_id in sorted(sequence_by_uav):
        uav = uav_by_id[uav_id]
        seq = sorted(sequence_by_uav[uav_id], key=lambda a: a["sequence_index"])
        for pos, a in enumerate(seq):
            source = mission_source[a["mission_id"]]
            path_options = [path_metrics(paths[pid], corridor_by_id, uav["uav_type"], source["payload_kg"], scenario_id) for pid in source["admissible_path_ids"]]
            compatible = [p for p in path_options if p["compatible"]]
            if not compatible:
                raise ValueError(f"BASELINE_INVALID_INCOMPATIBLE_UAV_PATH:{source['mission_id']}")
            if source["payload_kg"] > uav["payload_capacity_kg"] + 1e-9:
                raise ValueError(f"BASELINE_INVALID_PAYLOAD_CAPACITY:{source['mission_id']}")
            incoming = None
            if a["deadhead_path_id"]:
                incoming = path_metrics(paths[a["deadhead_path_id"]], corridor_by_id, uav["uav_type"], 0.0, scenario_id)
                if not incoming["compatible"]:
                    raise ValueError(f"BASELINE_INVALID_INCOMPATIBLE_DEADHEAD:{source['mission_id']}")
                expected_origin = uav["start_vertiport"] if pos == 0 else mission_source[seq[pos - 1]["mission_id"]]["destination_vertiport"]
                if incoming["node_sequence"][0] != expected_origin or incoming["node_sequence"][-1] != source["origin_vertiport"]:
                    raise ValueError(f"BASELINE_INVALID_DEADHEAD_ENDPOINT:{source['mission_id']}")
            preferred = next((p for p in compatible if p["path_id"] == a["service_path_id"]), min(compatible, key=lambda p: (p["travel_slots"], p["energy_kwh"], p["path_id"])))
            incoming_slots = incoming["travel_slots"] if incoming else 0
            earliest = max(math.ceil(source["release_time_min"] / SLOT_MIN), nominal_clock[uav_id] + incoming_slots)
            nominal_arrival = earliest + preferred["travel_slots"]
            slack_slots = {"easy": 8, "medium": 5, "hard": 3}[parent_scenario["difficulty"]]
            due = nominal_arrival + slack_slots
            min_energy = min(p["energy_kwh"] for p in compatible) + (incoming["energy_kwh"] if incoming else 0.0)
            min_energy_by_uav[uav_id] += min_energy
            compiled_missions.append({
                "mission_id": source["mission_id"], "uav_id": uav_id, "sequence_index": a["sequence_index"],
                "origin_vertiport": source["origin_vertiport"], "destination_vertiport": source["destination_vertiport"],
                "payload_kg": source["payload_kg"], "priority": source["priority"],
                "release_slot": earliest, "due_slot": due, "preferred_construction_path_id": preferred["path_id"],
                "path_options": path_options, "incoming_deadhead": incoming,
                "expected_incoming_origin_vertiport": uav["start_vertiport"] if pos == 0 else mission_source[seq[pos - 1]["mission_id"]]["destination_vertiport"],
            })
            nominal_clock[uav_id] = nominal_arrival + TURNAROUND_SLOTS
    family = parent_scenario["scenario_family"]
    for uav in fleet:
        required = min_energy_by_uav[uav["uav_id"]]
        if family in {"charger_capacity_repair", "soc_degradation_repair", "composed_resource_repair"}:
            deficit_blocks = 1 if parent_scenario["difficulty"] != "hard" else 2
            initial = uav["reserve_kwh"] + required - deficit_blocks * uav["charge_kwh_per_block"] + 0.15
        else:
            initial = uav["reserve_kwh"] + required + {"easy": 2.4, "medium": 1.5, "hard": 0.8}[parent_scenario["difficulty"]]
        uav["initial_soc_kwh"] = round(min(uav["battery_capacity_kwh"] - 0.5, max(uav["reserve_kwh"] + 1.0, initial)), 6)
    corridor_capacity = {c["corridor_id"]: max(1, min(2, c.get("capacity_per_slot", 2))) for c in corridors}
    pad_capacity = {v["vertiport_id"]: max(1, min(2, v["pad_capacity"])) for v in vps}
    charger_capacity = {v["vertiport_id"]: max(1, min(2, v["charger_count"])) for v in vps}
    horizon = max(m["due_slot"] for m in compiled_missions) + 12
    instance = {
        "artifact_flags": FLAGS, "instance_version": INSTANCE_VERSION, "model_version": MODEL_VERSION,
        "instance_id": f"{scenario_id}__{regime}", "scenario_id": scenario_id,
        "parent_phase_minus1b_scenario_id": parent_scenario["scenario_id"],
        "parent_scenario_content_sha256": parent_scenario["provenance"]["scenario_content_sha256"],
        "parent_skeleton_content_sha256": parent_skeleton["provenance"]["skeleton_content_sha256"],
        "split": parent_scenario["split"], "difficulty": parent_scenario["difficulty"], "ood_axis": parent_scenario["ood_axis"],
        "pool_role": pool_role, "topology_motif": parent_scenario["topology_motif"], "scenario_family": family,
        "preregistered_regime": regime, "slot_min": SLOT_MIN, "turnaround_slots": TURNAROUND_SLOTS,
        "max_charge_blocks": MAX_CHARGE_BLOCKS, "horizon_slots": horizon,
        "assignment_order_contract": "FIXED_UAV_ASSIGNMENT_AND_FIXED_UAV_ORDER",
        "deadhead_contract": "FIXED_REGISTERED_INCOMING_DEADHEAD_PATH; deadhead takeoff/landing and service takeoff/landing each consume one pad movement; one turnaround slot separates deadhead landing from service takeoff and service landing from charge/next operation; no deadhead rerouting",
        "fleet": fleet, "missions": sorted(compiled_missions, key=lambda m: (m["uav_id"], m["sequence_index"])),
        "resources": {"corridor_capacity_by_slot_default": corridor_capacity, "pad_capacity_by_slot_default": pad_capacity, "charger_capacity_by_slot_default": charger_capacity},
        "topology": {"vertiports": vps, "corridors": corridors},
        "provenance": {"generator_version": "generate_integrated_repair_phase_minus1d_pool_v1", "generator_sha256": generator_hash, "parent_entry": parent_entry,
                       "compatibility_override_count": 0, "uav_type_regeneration_count": uav_type_regeneration_count, "rejected_parent_count": 0},
    }
    instance["structural_signatures"] = structural_signatures(instance)
    instance["instance_sha256"] = sha256_obj(instance)
    return instance


def structural_signatures(instance):
    exact = {
        "motif": instance["topology_motif"], "family": instance["scenario_family"], "difficulty": instance["difficulty"],
        "edges": sorted((c["from_vertiport"], c["to_vertiport"], c["corridor_id"]) for c in instance["topology"]["corridors"]),
        "missions": [(m["uav_id"], m["sequence_index"], m["origin_vertiport"], m["destination_vertiport"], [p["path_id"] for p in m["path_options"]]) for m in instance["missions"]],
    }
    coarse = {
        "motif": instance["topology_motif"], "family": instance["scenario_family"], "difficulty": instance["difficulty"],
        "n_uav": len(instance["fleet"]), "n_mission": len(instance["missions"]), "n_edge": len(instance["topology"]["corridors"]),
        "path_count_hist": sorted(Counter(sum(p["compatible"] for p in m["path_options"]) for m in instance["missions"]).items()),
        "sequence_lengths": sorted(Counter(m["uav_id"] for m in instance["missions"]).values()),
    }
    template = {
        "motif": instance["topology_motif"], "family": instance["scenario_family"], "difficulty": instance["difficulty"],
        "n_uav": len(instance["fleet"]), "n_mission": len(instance["missions"]),
    }
    return {"exact_sha256": sha256_obj(exact), "coarse_sha256": sha256_obj(coarse), "template_sha256": sha256_obj(template)}


def empty_intervention(instance):
    return {
        "artifact_flags": FLAGS, "compiler_version": COMPILER_VERSION, "instance_id": instance["instance_id"],
        "family": instance["scenario_family"], "regime": "baseline", "operations": [],
        "closed_corridor_slots": [], "corridor_capacity_overrides": [], "pad_capacity_overrides": [],
        "charger_capacity_overrides": [], "mission_window_overrides": [], "initial_soc_overrides": [],
        "target_selection_provenance": "none_preintervention", "before_after_allowlisted_diff": [],
    }


def effective_maps(instance, intervention):
    release = {m["mission_id"]: m["release_slot"] for m in instance["missions"]}
    due = {m["mission_id"]: m["due_slot"] for m in instance["missions"]}
    initial_soc = {u["uav_id"]: u["initial_soc_kwh"] for u in instance["fleet"]}
    for x in intervention.get("mission_window_overrides", []):
        release[x["mission_id"]] = x.get("release_slot", release[x["mission_id"]])
        due[x["mission_id"]] = x.get("due_slot", due[x["mission_id"]])
    for x in intervention.get("initial_soc_overrides", []):
        initial_soc[x["uav_id"]] = x["initial_soc_kwh"]
    closed = {(x["corridor_id"], int(x["slot"])) for x in intervention.get("closed_corridor_slots", [])}
    corr_override = {(x["corridor_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("corridor_capacity_overrides", [])}
    pad_override = {(x["vertiport_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("pad_capacity_overrides", [])}
    charger_override = {(x["vertiport_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("charger_capacity_overrides", [])}
    return release, due, initial_soc, closed, corr_override, pad_override, charger_override


def shifted_edge_occupancy(path, start_slot):
    if not path:
        return []
    out = []
    for seg in path["edge_segments"]:
        for slot in range(start_slot + seg["offset_slot"], start_slot + seg["offset_slot"] + seg["duration_slots"]):
            out.append((seg["corridor_id"], slot))
    return out


def candidate_options(instance, intervention, mission, baseline_entry=None, ignore_intervention=False):
    uav = next(u for u in instance["fleet"] if u["uav_id"] == mission["uav_id"])
    if mission["payload_kg"] > uav["payload_capacity_kg"] + 1e-9:
        return []
    release, due, _, closed, _, _, _ = effective_maps(instance, intervention)
    options = []
    incoming = mission.get("incoming_deadhead")
    if incoming and not incoming.get("compatible", False):
        return []
    if incoming and (incoming["node_sequence"][0] != mission["expected_incoming_origin_vertiport"] or incoming["node_sequence"][-1] != mission["origin_vertiport"]):
        return []
    incoming_slots = incoming["travel_slots"] if incoming else 0
    paths = [p for p in mission["path_options"] if p["compatible"]]
    if not paths:
        return []
    min_travel = min(p["travel_slots"] for p in paths)
    # Due is soft. Candidate truncation is based only on explicit horizon and
    # terminal completion; tardiness may exceed two slots.
    latest_depart = instance["horizon_slots"] - min_travel - TURNAROUND_SLOTS - MAX_CHARGE_BLOCKS
    for path in paths:
        for depart in range(release[mission["mission_id"]], latest_depart + 1):
            deadhead_arrival = depart - TURNAROUND_SLOTS if incoming else None
            deadhead_start = deadhead_arrival - incoming_slots if incoming else depart
            if deadhead_start < 0:
                continue
            service_occ = shifted_edge_occupancy(path, depart)
            deadhead_occ = shifted_edge_occupancy(incoming, deadhead_start)
            if not ignore_intervention and any(x in closed for x in service_occ + deadhead_occ):
                continue
            arrival = depart + path["travel_slots"]
            for blocks in range(MAX_CHARGE_BLOCKS + 1):
                charge_start = arrival + TURNAROUND_SLOTS
                if charge_start + blocks > instance["horizon_slots"]:
                    continue
                charge_energy = blocks * uav["charge_kwh_per_block"]
                options.append({
                    "mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "path_id": path["path_id"],
                    "depart_slot": depart, "arrival_slot": arrival, "charge_blocks": blocks,
                    "charge_start_slot": charge_start, "charge_energy_kwh": round(charge_energy, 6),
                    "deadhead_start_slot": deadhead_start, "deadhead_path_id": incoming["path_id"] if incoming else None,
                    "deadhead_arrival_slot": deadhead_arrival,
                    "deadhead_occupancy": deadhead_occ, "service_occupancy": service_occ,
                    "energy_kwh": round(path["energy_kwh"] + (incoming["energy_kwh"] if incoming else 0.0), 6),
                    "service_energy_kwh": path["energy_kwh"], "deadhead_energy_kwh": incoming["energy_kwh"] if incoming else 0.0,
                    "tardiness_slots": max(0, arrival - due[mission["mission_id"]]),
                    "delay_slots": max(0, depart - release[mission["mission_id"]]),
                    "takeoff_vertiport": mission["origin_vertiport"], "landing_vertiport": mission["destination_vertiport"],
                    "incoming_origin_vertiport": incoming["node_sequence"][0] if incoming and "node_sequence" in incoming else None,
                })
    return options


def build_model(instance, intervention, baseline_plan=None):
    missions = instance["missions"]
    options_by_mission = {}
    var_meta = []
    option_indices = defaultdict(list)
    hold_idx = {}
    for mission in missions:
        baseline_entry = None if baseline_plan is None else next(x for x in baseline_plan["decisions"] if x["mission_id"] == mission["mission_id"])
        opts = candidate_options(instance, intervention, mission, baseline_entry)
        options_by_mission[mission["mission_id"]] = opts
        for opt in opts:
            idx = len(var_meta); var_meta.append({"kind": "option", **opt}); option_indices[mission["mission_id"]].append(idx)
        hold_idx[mission["mission_id"]] = len(var_meta)
        var_meta.append({"kind": "hold", "mission_id": mission["mission_id"], "uav_id": mission["uav_id"]})
    n = len(var_meta)
    rows, lbs, ubs = [], [], []
    def add(coeffs, lb=-np.inf, ub=np.inf):
        rows.append(coeffs); lbs.append(lb); ubs.append(ub)
    # Exactly one option or hold.
    for m in missions:
        coeff = {i: 1.0 for i in option_indices[m["mission_id"]]}; coeff[hold_idx[m["mission_id"]]] = 1.0
        add(coeff, 1.0, 1.0)
    # Holds form a suffix under fixed assignment/order.
    by_uav = defaultdict(list)
    for m in missions: by_uav[m["uav_id"]].append(m)
    for seq in by_uav.values():
        seq.sort(key=lambda m: m["sequence_index"])
        for prev, cur in zip(seq, seq[1:]):
            add({hold_idx[prev["mission_id"]]: 1.0, hold_idx[cur["mission_id"]]: -1.0}, -np.inf, 0.0)
    # Fixed-order temporal linkage and first availability.
    for uav_id, seq in by_uav.items():
        seq.sort(key=lambda m: m["sequence_index"])
        uav = next(u for u in instance["fleet"] if u["uav_id"] == uav_id)
        first = seq[0]
        for i in option_indices[first["mission_id"]]:
            if var_meta[i]["deadhead_start_slot"] < uav["available_slot"]:
                add({i: 1.0}, -np.inf, 0.0)
        M = instance["horizon_slots"] + 10
        for prev, cur in zip(seq, seq[1:]):
            coeff = {hold_idx[cur["mission_id"]]: M}
            for i in option_indices[cur["mission_id"]]: coeff[i] = coeff.get(i, 0) + var_meta[i]["deadhead_start_slot"]
            for i in option_indices[prev["mission_id"]]: coeff[i] = coeff.get(i, 0) - (var_meta[i]["charge_start_slot"] + var_meta[i]["charge_blocks"])
            add(coeff, 0.0, np.inf)
    # Resource occupancy.
    _, _, _, _, corr_override, pad_override, charger_override = effective_maps(instance, intervention)
    corr_terms, pad_terms, charger_terms = defaultdict(dict), defaultdict(dict), defaultdict(dict)
    for idx, meta in enumerate(var_meta):
        if meta["kind"] != "option": continue
        for key in meta["service_occupancy"] + meta["deadhead_occupancy"]:
            corr_terms[key][idx] = corr_terms[key].get(idx, 0) + 1.0
        # incoming deadhead movements and service movements consume pad movement capacity.
        mission = next(m for m in missions if m["mission_id"] == meta["mission_id"])
        incoming = mission.get("incoming_deadhead")
        if incoming:
            pad_terms[(incoming["node_sequence"][0] if "node_sequence" in incoming else mission["origin_vertiport"], meta["deadhead_start_slot"])][idx] = 1.0
            pad_terms[(mission["origin_vertiport"], meta["deadhead_arrival_slot"])][idx] = pad_terms[(mission["origin_vertiport"], meta["deadhead_arrival_slot"])].get(idx, 0) + 1.0
        pad_terms[(mission["origin_vertiport"], meta["depart_slot"])][idx] = pad_terms[(mission["origin_vertiport"], meta["depart_slot"])].get(idx, 0) + 1.0
        pad_terms[(mission["destination_vertiport"], meta["arrival_slot"])][idx] = pad_terms[(mission["destination_vertiport"], meta["arrival_slot"])].get(idx, 0) + 1.0
        for slot in range(meta["charge_start_slot"], meta["charge_start_slot"] + meta["charge_blocks"]):
            charger_terms[(mission["destination_vertiport"], slot)][idx] = 1.0
    corr_default = instance["resources"]["corridor_capacity_by_slot_default"]
    pad_default = instance["resources"]["pad_capacity_by_slot_default"]
    charger_default = instance["resources"]["charger_capacity_by_slot_default"]
    for key, coeff in corr_terms.items(): add(coeff, -np.inf, corr_override.get(key, corr_default[key[0]]))
    for key, coeff in pad_terms.items(): add(coeff, -np.inf, pad_override.get(key, pad_default[key[0]]))
    for key, coeff in charger_terms.items(): add(coeff, -np.inf, charger_override.get(key, charger_default[key[0]]))
    # SOC prefix and battery upper bound after each charge.
    _, _, initial_soc, _, _, _, _ = effective_maps(instance, intervention)
    for uav_id, seq in by_uav.items():
        seq.sort(key=lambda m: m["sequence_index"])
        uav = next(u for u in instance["fleet"] if u["uav_id"] == uav_id)
        for k in range(len(seq)):
            reserve_coeff, cap_coeff = {}, {}
            for j in range(k + 1):
                mid = seq[j]["mission_id"]
                for i in option_indices[mid]:
                    reserve_coeff[i] = reserve_coeff.get(i, 0) + var_meta[i]["energy_kwh"]
                    cap_coeff[i] = cap_coeff.get(i, 0) - var_meta[i]["energy_kwh"] + var_meta[i]["charge_energy_kwh"]
                    if j < k:
                        reserve_coeff[i] -= var_meta[i]["charge_energy_kwh"]
            add(reserve_coeff, -np.inf, initial_soc[uav_id] - uav["reserve_kwh"])
            add(cap_coeff, -np.inf, uav["battery_capacity_kwh"] - initial_soc[uav_id])
    # Objective vectors.
    tiers = []
    urgent = np.zeros(n); holds = np.zeros(n); repair = np.zeros(n); tardy = np.zeros(n); delay = np.zeros(n); energy = np.zeros(n)
    mission_map = {m["mission_id"]: m for m in missions}
    baseline_map = {} if baseline_plan is None else {d["mission_id"]: d for d in baseline_plan["decisions"]}
    for i, meta in enumerate(var_meta):
        m = mission_map[meta["mission_id"]]
        if meta["kind"] == "hold":
            urgent[i] = 1 if m["priority"] == "urgent" else 0
            holds[i] = 1
            repair[i] = 1000
            continue
        tardy[i] = meta["tardiness_slots"] * SLOT_MIN * (10 if m["priority"] == "urgent" else 1)
        delay[i] = meta["delay_slots"] * SLOT_MIN + meta["charge_blocks"] * SLOT_MIN
        energy[i] = meta["energy_kwh"]
        if baseline_plan is not None:
            b = baseline_map[meta["mission_id"]]
            if not b["held"]:
                repair[i] = 20 * (meta["path_id"] != b["path_id"]) + abs(meta["depart_slot"] - b["depart_slot"])
                repair[i] += 10 * ((meta["charge_blocks"] > 0) != (b["charge_blocks"] > 0)) + 2 * abs(meta["charge_blocks"] - b["charge_blocks"])
    if baseline_plan is None:
        tiers = [("urgent_holds", urgent), ("total_holds", holds), ("weighted_tardiness_min", tardy), ("delay_and_charge_wait_min", delay), ("energy_kwh", energy)]
    else:
        tiers = [("urgent_holds", urgent), ("total_holds", holds), ("repair_distance", repair), ("weighted_tardiness_min", tardy), ("delay_and_charge_wait_min", delay), ("energy_kwh", energy)]
    # Sparse matrix.
    rr, cc, dd = [], [], []
    for r, coeff in enumerate(rows):
        for c, val in coeff.items():
            if abs(val) > 0:
                rr.append(r); cc.append(c); dd.append(val)
    A = coo_matrix((dd, (rr, cc)), shape=(len(rows), n)).tocsr()
    return {"var_meta": var_meta, "option_indices": option_indices, "hold_idx": hold_idx, "A": A, "lb": np.array(lbs), "ub": np.array(ubs), "tiers": tiers, "base_constraint_count": len(rows)}


def solve_sequential(instance, intervention, baseline_plan=None, time_limit=20.0, check_alternative=True):
    built = build_model(instance, intervention, baseline_plan)
    n = len(built["var_meta"])
    A = built["A"]; lb = built["lb"]; ub = built["ub"]
    tier_results = []; last = None
    start = time.perf_counter()
    for name, c in built["tiers"]:
        constraint = LinearConstraint(A, lb, ub)
        res = milp(c, integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)), constraints=constraint,
                   options={"time_limit": time_limit, "mip_rel_gap": 0.0, "presolve": True})
        if not res.success or res.status != 0:
            return {"status": "NONCANONICAL_PARTIAL", "solver_message": str(res.message), "failed_tier": name, "runtime_sec": time.perf_counter() - start}
        value = float(np.dot(c, res.x))
        tier_results.append({"name": name, "value": round(value, 8), "mip_gap": float(getattr(res, "mip_gap", 0.0) or 0.0), "node_count": int(getattr(res, "mip_node_count", 0) or 0)})
        # Carry exact integer/registered numerical bound.
        A = vstack([A, csr_matrix(c.reshape(1, -1))], format="csr")
        lb = np.append(lb, -np.inf); ub = np.append(ub, value + 1e-7)
        last = res
    decisions = []
    for mission in instance["missions"]:
        hid = built["hold_idx"][mission["mission_id"]]
        if last.x[hid] > 0.5:
            decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0})
        else:
            chosen = [i for i in built["option_indices"][mission["mission_id"]] if last.x[i] > 0.5]
            if len(chosen) != 1:
                raise RuntimeError(f"option extraction {mission['mission_id']} {chosen}")
            meta = built["var_meta"][chosen[0]]
            decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": False, "path_id": meta["path_id"], "depart_slot": meta["depart_slot"], "charge_blocks": meta["charge_blocks"]})
    plan = {
        "artifact_flags": FLAGS, "model_version": MODEL_VERSION, "instance_id": instance["instance_id"],
        "instance_sha256": instance["instance_sha256"], "intervention_sha256": intervention.get("intervention_sha256"),
        "status": "OPTIMAL", "decisions": decisions, "objective_vector": tier_results,
        "telemetry": {"runtime_sec": round(time.perf_counter() - start, 6), "variable_count": n, "constraint_count": built["base_constraint_count"],
                      "mip_gap": tier_results[-1]["mip_gap"], "node_count": sum(x["node_count"] for x in tier_results), "backend": "scipy.optimize.milp/HiGHS"},
    }
    plan["alternative_optimum_exists"] = False
    if check_alternative:
        selected = []
        for mission in instance["missions"]:
            hid = built["hold_idx"][mission["mission_id"]]
            if last.x[hid] > 0.5: selected.append(hid)
            else: selected.extend(i for i in built["option_indices"][mission["mission_id"]] if last.x[i] > 0.5)
        nogood = np.zeros(n); nogood[selected] = 1.0
        A2 = vstack([A, csr_matrix(nogood.reshape(1, -1))], format="csr")
        lb2 = np.append(lb, -np.inf); ub2 = np.append(ub, len(selected) - 1)
        final_c = built["tiers"][-1][1]
        alt = milp(final_c, integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)), constraints=LinearConstraint(A2, lb2, ub2),
                   options={"time_limit": time_limit, "mip_rel_gap": 0.0, "presolve": True})
        plan["alternative_optimum_exists"] = bool(alt.success and alt.status == 0)
        if plan["alternative_optimum_exists"]:
            alt_decisions = []
            for mission in instance["missions"]:
                hid = built["hold_idx"][mission["mission_id"]]
                if alt.x[hid] > 0.5:
                    alt_decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0})
                else:
                    selected_alt = [i for i in built["option_indices"][mission["mission_id"]] if alt.x[i] > 0.5]
                    if len(selected_alt) == 1:
                        meta = built["var_meta"][selected_alt[0]]
                        alt_decisions.append({"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": False, "path_id": meta["path_id"], "depart_slot": meta["depart_slot"], "charge_blocks": meta["charge_blocks"]})
            plan["alternative_optimum_decisions"] = alt_decisions
    plan["plan_sha256"] = sha256_obj(plan)
    return plan


def plan_activity(instance, plan, intervention=None):
    intervention = intervention or empty_intervention(instance)
    mission_map = {m["mission_id"]: m for m in instance["missions"]}
    corridor = Counter(); pad = Counter(); charger = Counter(); soc_margin = {}; details = {}
    fleet = {u["uav_id"]: u for u in instance["fleet"]}
    _, _, initial_soc, _, _, _, _ = effective_maps(instance, intervention)
    soc = dict(initial_soc)
    for d in sorted(plan["decisions"], key=lambda x: (x["uav_id"], mission_map[x["mission_id"]]["sequence_index"])):
        if d["held"]: continue
        m = mission_map[d["mission_id"]]
        opts = candidate_options(instance, intervention, m, ignore_intervention=True)
        match = [o for o in opts if o["path_id"] == d["path_id"] and o["depart_slot"] == d["depart_slot"] and o["charge_blocks"] == d["charge_blocks"]]
        if not match: continue
        o = match[0]
        for key in o["service_occupancy"] + o["deadhead_occupancy"]: corridor[key] += 1
        incoming = m.get("incoming_deadhead")
        if incoming:
            pad[(incoming["node_sequence"][0], o["deadhead_start_slot"])] += 1
            pad[(m["origin_vertiport"], o["deadhead_arrival_slot"])] += 1
        pad[(m["origin_vertiport"], o["depart_slot"])] += 1
        pad[(m["destination_vertiport"], o["arrival_slot"])] += 1
        for slot in range(o["charge_start_slot"], o["charge_start_slot"] + o["charge_blocks"]): charger[(m["destination_vertiport"], slot)] += 1
        soc[d["uav_id"]] -= o["energy_kwh"]
        margin_before_charge = soc[d["uav_id"]] - fleet[d["uav_id"]]["reserve_kwh"]
        soc[d["uav_id"]] += o["charge_energy_kwh"]
        soc_margin[d["mission_id"]] = margin_before_charge
        details[d["mission_id"]] = o
    return {"corridor": corridor, "pad": pad, "charger": charger, "soc_margin": soc_margin, "details": details}


def compile_intervention(instance, baseline_plan, compiler_hash):
    family, regime = instance["scenario_family"], instance["preregistered_regime"]
    activity = plan_activity(instance, baseline_plan)
    missions = {m["mission_id"]: m for m in instance["missions"]}
    decisions = [d for d in baseline_plan["decisions"] if not d["held"]]
    out = empty_intervention(instance)
    out.update({"family": family, "regime": regime, "baseline_plan_sha256": baseline_plan["plan_sha256"], "compiler_sha256": compiler_hash})
    operations, diffs = [], []
    def active_route_target():
        candidates = []
        for d in decisions:
            o = activity["details"][d["mission_id"]]
            m = missions[d["mission_id"]]
            for edge, slot in o["service_occupancy"]:
                alternatives = [p for p in m["path_options"] if p["compatible"] and p["path_id"] != d["path_id"] and edge not in p["corridor_ids"]]
                candidates.append((0 if alternatives else 1, -activity["corridor"][(edge, slot)], d["mission_id"], edge, slot, len(alternatives)))
        return min(candidates)
    route_target = None
    if family == "route_availability_repair" or family == "composed_resource_repair":
        _, _, mid, edge, slot, alt_count = active_route_target()
        route_target = next(d for d in decisions if d["mission_id"] == mid)
        if regime == "no_op":
            slot2 = instance["horizon_slots"] - 1
            out["closed_corridor_slots"].append({"corridor_id": edge, "slot": slot2})
            severity = "inactive_slot"
        elif regime == "binding":
            out["closed_corridor_slots"].append({"corridor_id": edge, "slot": slot})
            severity = "active_slot_single_edge"
        else:
            chosen = activity["details"][mid]
            for e, s in chosen["service_occupancy"]:
                for ss in range(max(0, s - 1), min(instance["horizon_slots"], s + 3)):
                    out["closed_corridor_slots"].append({"corridor_id": e, "slot": ss})
            severity = "active_path_multi_slot"
        operations.append({"type": "route_availability", "mission_id": mid, "uav_id": route_target["uav_id"], "corridor_id": edge, "baseline_slot": slot, "baseline_active_occupancy": activity["corridor"][(edge, slot)], "alternative_edge_disjoint_path_count": alt_count, "severity": severity})
    if family == "pad_capacity_repair":
        key, count = max(activity["pad"].items(), key=lambda kv: (kv[1], kv[0]))
        vp, slot = key
        cap = instance["resources"]["pad_capacity_by_slot_default"][vp]
        newcap = cap if regime == "no_op" else max(0, count - 1) if regime == "binding" else 0
        target_slot = instance["horizon_slots"] - 1 if regime == "no_op" else slot
        out["pad_capacity_overrides"].append({"vertiport_id": vp, "slot": target_slot, "capacity": newcap})
        operations.append({"type": "pad_capacity", "vertiport_id": vp, "baseline_slot": slot, "baseline_occupancy": count, "before_capacity": cap, "after_capacity": newcap})
    if family == "charger_capacity_repair":
        if not activity["charger"]:
            raise ValueError(f"charger family baseline has no charging: {instance['instance_id']}")
        key, count = max(activity["charger"].items(), key=lambda kv: (kv[1], kv[0]))
        vp, slot = key; cap = instance["resources"]["charger_capacity_by_slot_default"][vp]
        target_slot = instance["horizon_slots"] - 1 if regime == "no_op" else slot
        newcap = cap if regime == "no_op" else max(0, count - 1) if regime == "binding" else 0
        out["charger_capacity_overrides"].append({"vertiport_id": vp, "slot": target_slot, "capacity": newcap})
        operations.append({"type": "charger_capacity", "vertiport_id": vp, "baseline_slot": slot, "baseline_occupancy": count, "before_capacity": cap, "after_capacity": newcap})
    if family == "mission_window_repair":
        # Choose a non-first mission with a non-empty suffix so a binding
        # release shift propagates through fixed order instead of becoming a
        # last-mission local positive control.
        candidates = [d for d in decisions if missions[d["mission_id"]]["sequence_index"] > 0 and any(
            x["uav_id"] == d["uav_id"] and x["sequence_index"] > missions[d["mission_id"]]["sequence_index"] for x in instance["missions"]
        )]
        candidates = sorted(candidates, key=lambda d: (missions[d["mission_id"]]["sequence_index"], d["mission_id"]))
        if not candidates:
            raise ValueError(f"MISSION_WINDOW_NO_CASCADE_TARGET:{instance['instance_id']}")
        d = candidates[0]; o = activity["details"][d["mission_id"]]; m = missions[d["mission_id"]]
        if regime == "no_op": release, due = m["release_slot"], m["due_slot"]
        elif regime == "binding": release, due = o["depart_slot"] + 3, m["due_slot"]
        else: release, due = instance["horizon_slots"] + 1, m["due_slot"]
        out["mission_window_overrides"].append({"mission_id": d["mission_id"], "release_slot": release, "due_slot": due})
        affected = [x["mission_id"] for x in instance["missions"] if x["uav_id"] == d["uav_id"] and x["sequence_index"] >= m["sequence_index"]]
        operations.append({"type": "mission_window", "mission_id": d["mission_id"], "baseline_arrival_slot": o["arrival_slot"], "affected_suffix_missions": affected})
    if family == "soc_degradation_repair" or family == "composed_resource_repair":
        if family == "composed_resource_repair":
            route_mission = missions[route_target["mission_id"]]
            same_suffix = [d for d in decisions if d["uav_id"] == route_target["uav_id"] and missions[d["mission_id"]]["sequence_index"] >= route_mission["sequence_index"]]
            target = min(same_suffix, key=lambda d: (activity["soc_margin"].get(d["mission_id"], 1e9), d["mission_id"]))
        else:
            target = min(decisions, key=lambda d: (activity["soc_margin"].get(d["mission_id"], 1e9), d["mission_id"]))
        uav = next(u for u in instance["fleet"] if u["uav_id"] == target["uav_id"])
        margin = activity["soc_margin"][target["mission_id"]]
        if regime == "no_op": new_soc = uav["initial_soc_kwh"]
        elif regime == "binding": new_soc = max(uav["reserve_kwh"], uav["initial_soc_kwh"] - margin - 0.1)
        else: new_soc = uav["reserve_kwh"]
        out["initial_soc_overrides"].append({"uav_id": uav["uav_id"], "initial_soc_kwh": round(new_soc, 6)})
        affected_suffix = [m["mission_id"] for m in instance["missions"] if m["uav_id"] == uav["uav_id"] and m["sequence_index"] >= missions[target["mission_id"]]["sequence_index"]]
        operations.append({"type": "soc_degradation", "uav_id": uav["uav_id"], "mission_id": target["mission_id"], "affected_suffix_missions": affected_suffix, "baseline_min_margin_kwh": round(margin, 6), "before_initial_soc_kwh": uav["initial_soc_kwh"], "after_initial_soc_kwh": round(new_soc, 6)})
    out["operations"] = operations
    for key in ("closed_corridor_slots", "corridor_capacity_overrides", "pad_capacity_overrides", "charger_capacity_overrides", "mission_window_overrides", "initial_soc_overrides"):
        if out[key]: diffs.append({"field": key, "before": "baseline_instance", "after": out[key]})
    out["before_after_allowlisted_diff"] = diffs
    if family == "composed_resource_repair":
        out["composed_same_uav_context"] = {
            "target_uav_id": route_target["uav_id"], "route_target_mission_id": route_target["mission_id"],
            "soc_target_mission_id": next(op["mission_id"] for op in operations if op["type"] == "soc_degradation"),
            "affected_suffix_missions": next(op["affected_suffix_missions"] for op in operations if op["type"] == "soc_degradation"),
        }
    out["target_selection_provenance"] = "deterministic_solver_baseline_active_set_rule_v2_independent_reconstruction_required"
    out["intervention_sha256"] = sha256_obj(out)
    return out


def choose_local_option(instance, intervention, mission, baseline_entry, zero_charge=False):
    opts = candidate_options(instance, intervention, mission)
    if zero_charge:
        opts = [o for o in opts if o["charge_blocks"] == 0]
    if not opts:
        return {"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0}
    def key(o):
        return (20 * (o["path_id"] != baseline_entry["path_id"]) + abs(o["depart_slot"] - baseline_entry["depart_slot"]) + 2 * abs(o["charge_blocks"] - baseline_entry["charge_blocks"]), o["tardiness_slots"], o["energy_kwh"], o["path_id"], o["depart_slot"], o["charge_blocks"])
    o = min(opts, key=key)
    return {"mission_id": mission["mission_id"], "uav_id": mission["uav_id"], "held": False, "path_id": o["path_id"], "depart_slot": o["depart_slot"], "charge_blocks": o["charge_blocks"]}


def heuristic_plans(instance, intervention, baseline_plan, oracle_plan):
    base_map = {d["mission_id"]: d for d in baseline_plan["decisions"]}
    plans = {}
    plans["baseline_copy"] = make_plan(instance, intervention, "baseline_copy", copy.deepcopy(baseline_plan["decisions"]))
    # No independent public preferred-field plan is materialized in the Phase
    # -1C-R instance. Preserve the control but declare it an alias rather than
    # double-counting an identical baseline.
    plans["field_copy"] = make_plan(instance, intervention, "field_copy", copy.deepcopy(baseline_plan["decisions"]))
    plans["field_copy"]["baseline_alias_status"] = "ALIAS_OF_BASELINE_COPY"
    plans["field_copy"]["independent_baseline"] = False
    plans["field_copy"]["plan_sha256"] = sha256_obj({k: v for k, v in plans["field_copy"].items() if k != "plan_sha256"})
    # Pure local route/time greedy uses a zero-charge policy and therefore does
    # not silently solve SOC or shared-resource coupling.
    greedy = [choose_local_option(instance, intervention, m, base_map[m["mission_id"]], zero_charge=True) for m in instance["missions"]]
    plans["greedy_route_time_repair"] = make_plan(instance, intervention, "greedy_route_time_repair", greedy)
    # SOC-oblivious uses the coupled route/time/shared-resource MILP after
    # explicitly relaxing battery/reserve and then materializes only decisions.
    relaxed = copy.deepcopy(instance)
    for u in relaxed["fleet"]:
        u["initial_soc_kwh"] = 10000.0; u["battery_capacity_kwh"] = 20000.0; u["reserve_kwh"] = 0.0
    relaxed_intervention = copy.deepcopy(intervention); relaxed_intervention["initial_soc_overrides"] = []
    relaxed_soc = solve_sequential(relaxed, relaxed_intervention, baseline_plan, check_alternative=False)
    soc_decisions = relaxed_soc.get("decisions", [choose_local_option(instance, intervention, m, base_map[m["mission_id"]], zero_charge=True) for m in instance["missions"]])
    for d in soc_decisions:
        if not d.get("held"):
            d["charge_blocks"] = 0
    plans["soc_oblivious_repair"] = make_plan(instance, intervention, "soc_oblivious_repair", soc_decisions)
    # Resource-oblivious is a per-UAV sequential SOC/charging heuristic. It
    # enforces fixed order and battery physics but never sees shared capacities.
    resource_decisions = []
    missions_by_uav = defaultdict(list)
    for m in instance["missions"]: missions_by_uav[m["uav_id"]].append(m)
    effective_initial = effective_maps(instance, intervention)[2]
    for uav_id, seq in sorted(missions_by_uav.items()):
        seq.sort(key=lambda m: m["sequence_index"])
        uav = next(u for u in instance["fleet"] if u["uav_id"] == uav_id)
        clock, soc, held = uav["available_slot"], effective_initial[uav_id], False
        for m in seq:
            if held:
                resource_decisions.append({"mission_id": m["mission_id"], "uav_id": uav_id, "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0}); continue
            opts = [o for o in candidate_options(instance, intervention, m, ignore_intervention=False) if o["deadhead_start_slot"] >= clock]
            feasible = [o for o in opts if soc - o["energy_kwh"] >= uav["reserve_kwh"] - 1e-9 and soc - o["energy_kwh"] + o["charge_energy_kwh"] <= uav["battery_capacity_kwh"] + 1e-9]
            if not feasible:
                # Conservative fail-safe: this resource-oblivious policy does
                # not compute an optimal suffix boundary. If its sequential
                # construction fails, it holds the entire UAV tour.
                held = True
                for prior in resource_decisions:
                    if prior["uav_id"] == uav_id:
                        prior.update({"held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0})
                resource_decisions.append({"mission_id": m["mission_id"], "uav_id": uav_id, "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0}); continue
            b = base_map[m["mission_id"]]
            o = min(feasible, key=lambda x: (x["tardiness_slots"], x["depart_slot"], x["energy_kwh"], x["charge_blocks"], x["path_id"]))
            resource_decisions.append({"mission_id": m["mission_id"], "uav_id": uav_id, "held": False, "path_id": o["path_id"], "depart_slot": o["depart_slot"], "charge_blocks": o["charge_blocks"]})
            soc = soc - o["energy_kwh"] + o["charge_energy_kwh"]; clock = o["charge_start_slot"] + o["charge_blocks"]
    plans["resource_oblivious_repair"] = make_plan(instance, intervention, "resource_oblivious_repair", resource_decisions)
    hold = [{"mission_id": m["mission_id"], "uav_id": m["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0} for m in instance["missions"]]
    plans["hold_all"] = make_plan(instance, intervention, "hold_all", hold)
    oracle = copy.deepcopy(oracle_plan); oracle["strategy"] = "solver_oracle"
    plans["solver_oracle"] = oracle
    return plans


def make_plan(instance, intervention, strategy, decisions):
    plan = {"artifact_flags": FLAGS, "model_version": f"deterministic_baseline::{strategy}", "strategy": strategy,
            "instance_id": instance["instance_id"], "instance_sha256": instance["instance_sha256"],
            "intervention_sha256": intervention.get("intervention_sha256"), "status": "CANDIDATE", "decisions": decisions,
            "claimed_changed_decisions": []}
    plan["plan_sha256"] = sha256_obj(plan)
    return plan
