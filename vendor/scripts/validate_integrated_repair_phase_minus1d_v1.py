#!/usr/bin/env python3
"""Independent Phase -1D verifier; intentionally does not import solver code."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


FLAGS = {"ANALYSIS_ONLY", "PREVIEW_NOT_RELEASE", "NOT_A_BENCHMARK_REFERENCE", "NO_MODEL_API"}
SLOT_MIN = 5
TURNAROUND_SLOTS = 1
VALIDATOR_VERSION = "validate_integrated_repair_phase_minus1d_v1"
EXPECTED_INSTANCE_VERSION = "integrated_repair_phase_minus1d_instance_v1"
EXPECTED_MODEL_VERSION = "integrated_repair_phase_minus1d_calibration_milp_v1"
EXPECTED_COMPILER_VERSION = "integrated_repair_phase_minus1d_intervention_compiler_v1"


def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_without(obj, key):
    clone = copy.deepcopy(obj); clone.pop(key, None)
    return hashlib.sha256(canonical_bytes(clone)).hexdigest()


def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path, rows, fields):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def effective(instance, intervention):
    release = {m["mission_id"]: m["release_slot"] for m in instance["missions"]}
    due = {m["mission_id"]: m["due_slot"] for m in instance["missions"]}
    initial = {u["uav_id"]: u["initial_soc_kwh"] for u in instance["fleet"]}
    for x in intervention.get("mission_window_overrides", []):
        release[x["mission_id"]] = x["release_slot"]; due[x["mission_id"]] = x["due_slot"]
    for x in intervention.get("initial_soc_overrides", []): initial[x["uav_id"]] = x["initial_soc_kwh"]
    closed = {(x["corridor_id"], int(x["slot"])) for x in intervention.get("closed_corridor_slots", [])}
    corr = {(x["corridor_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("corridor_capacity_overrides", [])}
    pad = {(x["vertiport_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("pad_capacity_overrides", [])}
    charger = {(x["vertiport_id"], int(x["slot"])): int(x["capacity"]) for x in intervention.get("charger_capacity_overrides", [])}
    return release, due, initial, closed, corr, pad, charger


def recompute_path(path, mission, uav, corridors):
    current = mission["origin_vertiport"] if mission else path["node_sequence"][0]
    payload = mission["payload_kg"] if mission else 0.0
    distance = 0.0; offset = 0; occ = []; winds = []; layers = set()
    for seg, cid in zip(path["edge_segments"], path["corridor_ids"]):
        if cid not in corridors: return None, "UNKNOWN_CORRIDOR"
        c = corridors[cid]
        if not c.get("authorized", True) or c.get("weather_closed", False) or c.get("no_fly", False): return None, "INCOMPATIBLE_CORRIDOR_STATUS"
        layers.add(c["altitude_layer"])
        if c["from_vertiport"] != current: return None, "SPATIAL_DISCONTINUITY"
        if seg["corridor_id"] != cid or seg["offset_slot"] != offset: return None, "PATH_SEGMENT_MISMATCH"
        duration = max(1, math.ceil((c["base_travel_time_min"] * uav["travel_time_coefficient"] * (1 + 0.06 * seg["wind_level"])) / SLOT_MIN))
        if duration != seg["duration_slots"]: return None, "TRAVEL_TIME_COEFFICIENT_MISMATCH"
        distance += c["distance_km"]; winds.append(seg["wind_level"])
        occ.extend((cid, offset + k) for k in range(duration)); offset += duration; current = c["to_vertiport"]
    expected_dest = mission["destination_vertiport"] if mission else path["node_sequence"][-1]
    if current != expected_dest: return None, "PATH_ENDPOINT_MISMATCH"
    if max(winds, default=0) > uav["max_wind_level"] or not layers.issubset(set(uav["compatible_layers"])): return None, "INCOMPATIBLE_UAV_PATH"
    if mission and mission["payload_kg"] > uav["payload_capacity_kg"] + 1e-9: return None, "PAYLOAD_CAPACITY_VIOLATION"
    energy = distance * (uav["empty_energy_kwh_per_km"] + payload * uav["payload_energy_kwh_per_km_kg"])
    energy *= 1 + uav["wind_energy_multiplier_per_level"] * (sum(winds) / max(1, len(winds)))
    if abs(energy - path["energy_kwh"]) > 1e-5: return None, "ENERGY_COEFFICIENT_MISMATCH"
    return {"travel_slots": offset, "energy_kwh": energy, "relative_occupancy": occ}, None


def validate_plan(instance, intervention, plan, baseline=None, oracle=None):
    errors = []
    def err(code, detail=""): errors.append({"code": code, "detail": str(detail)})
    if not FLAGS.issubset(set(plan.get("artifact_flags", []))): err("PREVIEW_FLAGS")
    if instance.get("instance_version") != EXPECTED_INSTANCE_VERSION or instance.get("model_version") != EXPECTED_MODEL_VERSION: err("MODEL_LINEAGE_MISMATCH", "instance")
    if instance.get("turnaround_slots") != TURNAROUND_SLOTS: err("DEADHEAD_SERVICE_TURNAROUND_VIOLATION", "registered turnaround")
    if intervention.get("compiler_version") not in (None, EXPECTED_COMPILER_VERSION): err("COMPILER_LINEAGE_MISMATCH")
    if plan.get("instance_id") != instance["instance_id"]: err("INSTANCE_ID_MISMATCH")
    if plan.get("instance_sha256") != instance["instance_sha256"]: err("STALE_BASELINE_HASH", "instance hash")
    if intervention.get("intervention_sha256") and plan.get("intervention_sha256") != intervention["intervention_sha256"]: err("INTERVENTION_MISMATCH")
    if plan.get("plan_sha256") and hash_without(plan, "plan_sha256") != plan["plan_sha256"]: err("PLAN_HASH_MISMATCH")
    if baseline is not None and intervention.get("baseline_plan_sha256") != baseline.get("plan_sha256"): err("BASELINE_HASH_MISMATCH")
    missions = {m["mission_id"]: m for m in instance["missions"]}
    uavs = {u["uav_id"]: u for u in instance["fleet"]}
    corridors = {c["corridor_id"]: c for c in instance["topology"]["corridors"]}
    decisions = plan.get("decisions", [])
    ids = [d.get("mission_id") for d in decisions]
    if set(ids) != set(missions) or len(ids) != len(set(ids)) or len(ids) != len(missions): err("DUPLICATE_MISSING_EXTRA_ID", f"{len(ids)}/{len(missions)}")
    unknown_uav = [d.get("uav_id") for d in decisions if d.get("uav_id") not in uavs]
    if unknown_uav: err("UNKNOWN_UAV", unknown_uav[:3])
    unknown_path = []
    release, due, initial, closed, corr_override, pad_override, charger_override = effective(instance, intervention)
    corr_occ, pad_occ, charger_occ = Counter(), Counter(), Counter()
    by_uav = defaultdict(list)
    for d in decisions:
        if d.get("mission_id") in missions: by_uav[missions[d["mission_id"]]["uav_id"]].append(d)
    total_holds = urgent_holds = route_changes = charge_activations = charge_blocks = 0
    total_depart_shift = total_tardiness = delay_charge = energy_total = 0.0
    min_soc_margin = float("inf"); reserve_bindings = 0; max_cascade = 0
    baseline_map = {} if baseline is None else {d["mission_id"]: d for d in baseline["decisions"]}
    reconstructed = {}
    for uav_id, seq_decisions in by_uav.items():
        seq_decisions.sort(key=lambda d: missions[d["mission_id"]]["sequence_index"])
        expected_seq = sorted((m for m in missions.values() if m["uav_id"] == uav_id), key=lambda m: m["sequence_index"])
        held_seen = False; prev_charge_end = uavs[uav_id]["available_slot"]; soc = initial[uav_id]; served = 0
        for mission, d in zip(expected_seq, seq_decisions):
            if d.get("uav_id") != uav_id: err("ASSIGNMENT_MISMATCH", mission["mission_id"])
            if d.get("held"):
                held_seen = True; total_holds += 1; urgent_holds += mission["priority"] == "urgent"
                continue
            if held_seen: err("NON_SUFFIX_HOLD", mission["mission_id"])
            served += 1
            paths = {p["path_id"]: p for p in mission["path_options"] if p["compatible"]}
            if d.get("path_id") not in paths:
                unknown_path.append(d.get("path_id")); err("UNKNOWN_PATH", mission["mission_id"]); continue
            path = paths[d["path_id"]]
            if mission["payload_kg"] > uavs[uav_id]["payload_capacity_kg"] + 1e-9: err("PAYLOAD_CAPACITY_VIOLATION", mission["mission_id"]); continue
            rec, code = recompute_path(path, mission, uavs[uav_id], corridors)
            if code: err(code, mission["mission_id"]); continue
            incoming = mission.get("incoming_deadhead")
            dh_rec = {"travel_slots": 0, "energy_kwh": 0.0, "relative_occupancy": []}
            if incoming:
                if not incoming.get("compatible", False): err("INCOMPATIBLE_DEADHEAD", mission["mission_id"]); continue
                if incoming["node_sequence"][0] != mission.get("expected_incoming_origin_vertiport"):
                    err("DEADHEAD_START_ENDPOINT_MISMATCH", mission["mission_id"]); continue
                if incoming["node_sequence"][-1] != mission["origin_vertiport"]:
                    err("DEADHEAD_DESTINATION_MISMATCH", mission["mission_id"]); continue
                dummy = {"origin_vertiport": incoming["node_sequence"][0], "destination_vertiport": mission["origin_vertiport"], "payload_kg": 0.0}
                dh_rec, code = recompute_path(incoming, dummy, uavs[uav_id], corridors)
                if code: err("INCOMPATIBLE_DEADHEAD" if code == "INCOMPATIBLE_UAV_PATH" else code, f"deadhead:{mission['mission_id']}"); continue
            depart = d.get("depart_slot")
            blocks = d.get("charge_blocks")
            if not isinstance(depart, int) or not isinstance(blocks, int) or blocks < 0 or blocks > instance["max_charge_blocks"]:
                err("DOMAIN_VIOLATION", mission["mission_id"]); continue
            dh_arrival = depart - TURNAROUND_SLOTS if incoming else None
            dh_start = dh_arrival - dh_rec["travel_slots"] if incoming else depart
            if depart < release[mission["mission_id"]] or dh_start < prev_charge_end: err("FIXED_ORDER_TIME_VIOLATION", mission["mission_id"])
            if incoming and depart - dh_arrival < TURNAROUND_SLOTS: err("DEADHEAD_SERVICE_TURNAROUND_VIOLATION", mission["mission_id"])
            arrival = depart + rec["travel_slots"]
            for cid, rel in dh_rec["relative_occupancy"]:
                key = (cid, dh_start + rel); corr_occ[key] += 1
                if key in closed: err("CLOSED_CORRIDOR_SUBMISSION", f"{mission['mission_id']}:{key}")
            for cid, rel in rec["relative_occupancy"]:
                key = (cid, depart + rel); corr_occ[key] += 1
                if key in closed: err("CLOSED_CORRIDOR_SUBMISSION", f"{mission['mission_id']}:{key}")
            if incoming: pad_occ[(incoming["node_sequence"][0], dh_start)] += 1
            if incoming: pad_occ[(mission["origin_vertiport"], dh_arrival)] += 1
            pad_occ[(mission["origin_vertiport"], depart)] += 1
            pad_occ[(mission["destination_vertiport"], arrival)] += 1
            charge_start = arrival + TURNAROUND_SLOTS
            for slot in range(charge_start, charge_start + blocks): charger_occ[(mission["destination_vertiport"], slot)] += 1
            energy = rec["energy_kwh"] + dh_rec["energy_kwh"]
            soc -= energy; margin = soc - uavs[uav_id]["reserve_kwh"]
            min_soc_margin = min(min_soc_margin, margin)
            if margin < -1e-6: err("SOC_RESERVE_VIOLATION", mission["mission_id"])
            if abs(margin) <= 1e-6: reserve_bindings += 1
            soc += blocks * uavs[uav_id]["charge_kwh_per_block"]
            if soc > uavs[uav_id]["battery_capacity_kwh"] + 1e-6: err("BATTERY_CAPACITY_VIOLATION", mission["mission_id"])
            prev_charge_end = charge_start + blocks
            total_tardiness += max(0, arrival - due[mission["mission_id"]]) * SLOT_MIN * (10 if mission["priority"] == "urgent" else 1)
            delay_charge += max(0, depart - release[mission["mission_id"]]) * SLOT_MIN + blocks * SLOT_MIN
            energy_total += energy; charge_blocks += blocks
            if baseline is not None:
                b = baseline_map[mission["mission_id"]]
                route_changes += d["path_id"] != b["path_id"]
                total_depart_shift += abs(depart - b["depart_slot"])
                charge_activations += (blocks > 0) != (b["charge_blocks"] > 0)
            reconstructed[mission["mission_id"]] = {"depart_slot": depart, "arrival_slot": arrival, "deadhead_start_slot": dh_start, "deadhead_arrival_slot": dh_arrival, "soc_margin_kwh": margin, "energy_kwh": energy}
        max_cascade = max(max_cascade, served)
    corr_default = instance["resources"]["corridor_capacity_by_slot_default"]
    pad_default = instance["resources"]["pad_capacity_by_slot_default"]
    charger_default = instance["resources"]["charger_capacity_by_slot_default"]
    corridor_binding = pad_binding = charger_binding = 0
    for key, val in corr_occ.items():
        cap = corr_override.get(key, corr_default[key[0]])
        if val > cap: err("CORRIDOR_CAPACITY_VIOLATION", f"{key}:{val}>{cap}")
        if val == cap: corridor_binding += 1
    for key, val in pad_occ.items():
        cap = pad_override.get(key, pad_default[key[0]])
        if val > cap: err("PAD_OVER_CAPACITY", f"{key}:{val}>{cap}")
        if val == cap: pad_binding += 1
    for key, val in charger_occ.items():
        cap = charger_override.get(key, charger_default[key[0]])
        if val > cap: err("CHARGER_OVER_CAPACITY", f"{key}:{val}>{cap}")
        if val == cap: charger_binding += 1
    repair_distance = 1000 * total_holds
    changed = []
    if baseline is not None:
        for d in decisions:
            b = baseline_map.get(d.get("mission_id"))
            if not b: continue
            if d.get("held"):
                if not b["held"]: changed.append(d["mission_id"]); continue
            elif b["held"] or d.get("path_id") != b.get("path_id") or d.get("depart_slot") != b.get("depart_slot") or d.get("charge_blocks") != b.get("charge_blocks"):
                changed.append(d["mission_id"])
            if not d.get("held") and not b["held"]:
                repair_distance += 20 * (d["path_id"] != b["path_id"]) + abs(d["depart_slot"] - b["depart_slot"])
                repair_distance += 10 * ((d["charge_blocks"] > 0) != (b["charge_blocks"] > 0)) + 2 * abs(d["charge_blocks"] - b["charge_blocks"])
    claim = plan.get("claimed_changed_decisions")
    if claim not in (None, []) and sorted(claim) != sorted(changed): err("FALSE_CHANGED_DECISION_CLAIM")
    objective = {
        "urgent_holds": int(urgent_holds), "total_holds": int(total_holds),
        "repair_distance": round(repair_distance, 6), "weighted_tardiness_min": round(total_tardiness, 6),
        "delay_and_charge_wait_min": round(delay_charge, 6), "energy_kwh": round(energy_total, 6),
    }
    if baseline is None: objective.pop("repair_distance")
    if plan.get("objective_vector"):
        claimed = {x["name"]: x["value"] for x in plan["objective_vector"]}
        for k, v in objective.items():
            if k in claimed and abs(claimed[k] - v) > 1e-4: err("OBJECTIVE_VECTOR_MISMATCH", k)
    oracle_match = None
    if oracle is not None and not errors:
        oracle_claimed = {x["name"]: x["value"] for x in oracle.get("objective_vector", [])}
        oracle_match = all(abs(objective.get(k, float("inf")) - v) <= 1e-4 for k, v in oracle_claimed.items())
    return {
        "valid": not errors, "feasible": not errors, "errors": errors, "objective": objective,
        "changed_decisions": sorted(changed), "route_changes": int(route_changes), "departure_shift_slots": total_depart_shift,
        "charge_activation_changes": int(charge_activations), "charge_blocks": int(charge_blocks),
        "corridor_binding_count": corridor_binding, "pad_binding_count": pad_binding, "charger_binding_count": charger_binding,
        "minimum_soc_margin_kwh": None if min_soc_margin == float("inf") else round(min_soc_margin, 6),
        "reserve_binding_count": reserve_bindings, "cascade_length": len(changed), "maximum_served_sequence_length": max_cascade,
        "oracle_objective_match": oracle_match, "reconstructed": reconstructed,
    }


def evaluate_submission(instance, intervention, plan, baseline=None, oracle=None):
    """Public evaluator wrapper: invalid submissions never receive score/gap data."""
    result = validate_plan(instance, intervention, plan, baseline=baseline, oracle=oracle)
    if not result["valid"]:
        result["objective"] = None
        result["objective_gap"] = None
        result["oracle_objective_match"] = None
    elif oracle is None:
        result["objective_gap"] = None
    else:
        names = ["urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh"]
        oracle_obj = {x["name"]: x["value"] for x in oracle.get("objective_vector", [])}
        result["objective_gap"] = {k: result["objective"][k] - oracle_obj[k] for k in names if k in oracle_obj}
    return result


def reconstruct_baseline_activity(instance, baseline):
    missions = {m["mission_id"]: m for m in instance["missions"]}; uavs = {u["uav_id"]: u for u in instance["fleet"]}
    corridors = {c["corridor_id"]: c for c in instance["topology"]["corridors"]}
    corr, pad, charger, details, soc_margin = Counter(), Counter(), Counter(), {}, {}
    soc = {u: x["initial_soc_kwh"] for u, x in uavs.items()}
    for d in sorted(baseline["decisions"], key=lambda x: (x["uav_id"], missions[x["mission_id"]]["sequence_index"])):
        if d["held"]: continue
        m, u = missions[d["mission_id"]], uavs[d["uav_id"]]
        p = next(x for x in m["path_options"] if x["path_id"] == d["path_id"])
        rec, code = recompute_path(p, m, u, corridors)
        if code: raise ValueError(code)
        incoming = m.get("incoming_deadhead"); dh_rec = {"travel_slots": 0, "energy_kwh": 0.0, "relative_occupancy": []}
        if incoming:
            dummy = {"origin_vertiport": incoming["node_sequence"][0], "destination_vertiport": m["origin_vertiport"], "payload_kg": 0.0}
            dh_rec, code = recompute_path(incoming, dummy, u, corridors)
            if code: raise ValueError(code)
        depart = d["depart_slot"]; arrival = depart + rec["travel_slots"]
        dh_arrival = depart - TURNAROUND_SLOTS if incoming else None
        dh_start = dh_arrival - dh_rec["travel_slots"] if incoming else depart
        for cid, rel in dh_rec["relative_occupancy"]: corr[(cid, dh_start + rel)] += 1
        for cid, rel in rec["relative_occupancy"]: corr[(cid, depart + rel)] += 1
        if incoming:
            pad[(incoming["node_sequence"][0], dh_start)] += 1; pad[(m["origin_vertiport"], dh_arrival)] += 1
        pad[(m["origin_vertiport"], depart)] += 1; pad[(m["destination_vertiport"], arrival)] += 1
        charge_start = arrival + TURNAROUND_SLOTS
        for slot in range(charge_start, charge_start + d["charge_blocks"]): charger[(m["destination_vertiport"], slot)] += 1
        soc[d["uav_id"]] -= rec["energy_kwh"] + dh_rec["energy_kwh"]
        soc_margin[d["mission_id"]] = soc[d["uav_id"]] - u["reserve_kwh"]
        soc[d["uav_id"]] += d["charge_blocks"] * u["charge_kwh_per_block"]
        details[d["mission_id"]] = {"uav_id": d["uav_id"], "depart_slot": depart, "arrival_slot": arrival}
    return {"corridor": corr, "pad": pad, "charger": charger, "soc_margin": soc_margin, "details": details}


def baseline_target_active(instance, intervention, baseline_plan):
    if intervention["regime"] == "no_op": return True
    activity = reconstruct_baseline_activity(instance, baseline_plan)
    route_uavs, soc_uavs = set(), set()
    for op in intervention["operations"]:
        if op["type"] == "route_availability":
            if activity["corridor"][(op["corridor_id"], int(op["baseline_slot"]))] <= 0: return False
            actual = activity["details"].get(op["mission_id"])
            if not actual: return False
            route_uavs.add(actual["uav_id"])
        elif op["type"] == "pad_capacity" and activity["pad"][(op["vertiport_id"], int(op["baseline_slot"]))] <= 0: return False
        elif op["type"] == "charger_capacity" and activity["charger"][(op["vertiport_id"], int(op["baseline_slot"]))] <= 0: return False
        elif op["type"] == "mission_window":
            actual = activity["details"].get(op["mission_id"])
            if not actual or actual["arrival_slot"] != int(op["baseline_arrival_slot"]): return False
        elif op["type"] == "soc_degradation":
            if op["mission_id"] not in activity["soc_margin"]: return False
            soc_uavs.add(op["uav_id"])
    if intervention.get("family") == "composed_resource_repair":
        context = intervention.get("composed_same_uav_context", {})
        if len(route_uavs) != 1 or route_uavs != soc_uavs or context.get("target_uav_id") not in route_uavs: return False
        if context.get("soc_target_mission_id") not in context.get("affected_suffix_missions", []): return False
    return True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--pool", required=True); args = ap.parse_args()
    pool = Path(args.pool).resolve(); manifest = load(pool / "PHASE_MINUS1D_CALIBRATION_POOL_MANIFEST.json")
    rows, failures, active_rows = [], [], []
    hard_failures = []
    if hash_without(manifest, "manifest_sha256") != manifest.get("manifest_sha256"):
        hard_failures.append({"instance_id": "MANIFEST", "strategy": "INTEGRITY", "code": "MANIFEST_HASH_MISMATCH", "detail": ""})
    expected_ids = [e["instance_id"] for e in manifest["entries"]]
    if len(expected_ids) != len(set(expected_ids)):
        hard_failures.append({"instance_id": "MANIFEST", "strategy": "INTEGRITY", "code": "DUPLICATE_INSTANCE_ID", "detail": ""})
    for entry in manifest["entries"]:
        instance_path = pool / entry["file"]
        instance = load(instance_path)
        file_sha256 = hashlib.sha256(instance_path.read_bytes()).hexdigest()
        if hash_without(instance, "instance_sha256") != instance["instance_sha256"] or file_sha256 != entry["file_sha256"]:
            hard_failures.append({"instance_id": instance["instance_id"], "strategy": "INSTANCE", "code": "INSTANCE_HASH_MISMATCH", "detail": ""})
        baseline = load(pool / "baselines" / f"{instance['instance_id']}_baseline.json")
        base_int = {"closed_corridor_slots": [], "corridor_capacity_overrides": [], "pad_capacity_overrides": [], "charger_capacity_overrides": [], "mission_window_overrides": [], "initial_soc_overrides": []}
        base = validate_plan(instance, base_int, baseline)
        if not base["valid"]:
            for e in base["errors"]: hard_failures.append({"instance_id": instance["instance_id"], "strategy": "baseline", **e})
        rows.append({"instance_id": instance["instance_id"], "split": instance["split"], "difficulty": instance["difficulty"], "family": instance["scenario_family"], "regime": "baseline", "strategy": "solver_derived_preintervention_baseline", **{k: v for k, v in base.items() if k not in {"errors", "objective", "reconstructed", "changed_decisions"}}, **base["objective"], "error_codes": "|".join(e["code"] for e in base["errors"])})
        intervention = load(pool / "interventions" / f"{instance['instance_id']}_intervention.json")
        if hash_without(intervention, "intervention_sha256") != intervention["intervention_sha256"]:
            hard_failures.append({"instance_id": instance["instance_id"], "strategy": "INTERVENTION", "code": "INTERVENTION_HASH_MISMATCH", "detail": ""})
        if intervention.get("compiler_version") != EXPECTED_COMPILER_VERSION:
            hard_failures.append({"instance_id": instance["instance_id"], "strategy": "INTERVENTION", "code": "COMPILER_LINEAGE_MISMATCH", "detail": ""})
        if intervention.get("baseline_plan_sha256") != baseline.get("plan_sha256"):
            hard_failures.append({"instance_id": instance["instance_id"], "strategy": "INTERVENTION", "code": "BASELINE_HASH_MISMATCH", "detail": ""})
        oracle = load(pool / "repairs" / f"{instance['instance_id']}_repair.json")
        active = baseline_target_active(instance, intervention, baseline)
        active_rows.append({"instance_id": instance["instance_id"], "family": intervention["family"], "regime": intervention["regime"], "independently_reconstructed_active": active,
                            "operation_types": "|".join(op["type"] for op in intervention["operations"]), "compiler_metadata_trusted": False,
                            "composed_same_uav": intervention["family"] != "composed_resource_repair" or active})
        if intervention["regime"] == "binding" and not active:
            hard_failures.append({"instance_id": instance["instance_id"], "strategy": "ACTIVE_SET", "code": "INVALID_ACTIVE_SET_CLAIM", "detail": ""})
        for plan_path in sorted((pool / "baseline_suite" / instance["instance_id"]).glob("*.json")):
            plan = load(plan_path); strategy = plan_path.stem
            result = validate_plan(instance, intervention, plan, baseline=baseline, oracle=oracle)
            if not result["valid"]:
                target = hard_failures if strategy == "solver_oracle" else failures
                for e in result["errors"]: target.append({"instance_id": instance["instance_id"], "strategy": strategy, **e})
            row = {"instance_id": instance["instance_id"], "split": instance["split"], "difficulty": instance["difficulty"], "family": instance["scenario_family"], "regime": intervention["regime"], "strategy": strategy,
                   "target_active_set_member": active, **{k: v for k, v in result.items() if k not in {"errors", "objective", "reconstructed", "changed_decisions"}}, **result["objective"],
                   "error_codes": "|".join(e["code"] for e in result["errors"]), "changed_decision_count": len(result["changed_decisions"])}
            rows.append(row)
    fields = sorted({k for r in rows for k in r})
    write_csv(pool / "validation" / "validation_records.csv", rows, fields)
    all_failures = [{**x, "severity": "EXPECTED_HEURISTIC"} for x in failures] + [{**x, "severity": "HARD"} for x in hard_failures]
    write_csv(pool / "validation" / "validation_failures.csv", all_failures, ["instance_id", "strategy", "code", "detail", "severity"])
    write_csv(pool / "validation" / "ACTIVE_SET_INDEPENDENT_VERIFICATION.csv", active_rows, ["instance_id", "family", "regime", "independently_reconstructed_active", "operation_types", "compiler_metadata_trusted", "composed_same_uav"])
    oracle_rows = [r for r in rows if r["strategy"] == "solver_oracle"]
    summary = {
        "artifact_flags": sorted(FLAGS), "validator_version": VALIDATOR_VERSION,
        "instance_count": len(manifest["entries"]), "record_count": len(rows), "failure_record_count": len(all_failures), "hard_failure_count": len(hard_failures), "expected_heuristic_failure_count": len(failures),
        "baseline_pass_count": sum(r["strategy"] == "solver_derived_preintervention_baseline" and r["valid"] for r in rows),
        "oracle_pass_count": sum(r["valid"] for r in oracle_rows),
        "binding_target_active_count": sum(r["target_active_set_member"] for r in oracle_rows if r["regime"] == "binding"),
        "binding_instance_count": sum(r["regime"] == "binding" for r in oracle_rows),
        "no_api": True, "formal_reference_count": 0,
    }
    write_json(pool / "validation" / "validation_summary.json", summary)
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["baseline_pass_count"] == len(manifest["entries"]) and summary["oracle_pass_count"] == len(manifest["entries"]) and not hard_failures else 1)


if __name__ == "__main__": main()
