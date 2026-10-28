"""Compare the frozen greedy policy under time-domain and SOC numeric changes.

Only public task fields enter candidate construction. Archived source files are
imported read-only; all new results are written beside this script.
"""
from __future__ import annotations

import copy
import csv
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore  # noqa: E402


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def exact_energy(path, mission, uav, corridors, deadhead=False):
    distance = sum(corridors[c]["distance_km"] for c in path["corridor_ids"])
    winds = [seg["wind_level"] for seg in path["edge_segments"]]
    return distance * (
        uav["empty_energy_kwh_per_km"]
        + (0 if deadhead else mission["payload_kg"]) * uav["payload_energy_kwh_per_km_kg"]
    ) * (1 + uav["wind_energy_multiplier_per_level"] * statistics.mean(winds))


def main():
    output = HERE / "policy_domains"
    output.mkdir(exist_ok=True)
    runtime = rescore.runtime()
    scorer, bridge, mods = runtime
    core = mods["core"]
    policy = rescore.load("greedy_original", PKG / "vendor/scripts/run_candidate_a_v12p1_resource_aware_greedy_baseline_v1.py")
    original_options = core.candidate_options
    original_feasible = policy.feasible_option
    original_priority = policy.local_priority
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PKG / "data/public/records").glob("CA12_CORE_*.json"))]
    archived = {r["record_id"]: json.loads(r["raw_text"])["decisions"] for r in rows(PKG / "responses/policy.jsonl")}
    summary = {}
    score_by_mode = {}
    decisions_by_mode = {}
    timings = {}
    for mode in ("archived_rules", "public_time", "public_numeric", "public_both"):
        out_rows, task_times = [], []
        scored, decisions_by_mode[mode] = {}, {}
        for index, task in enumerate(tasks, 1):
            instance, intervention, baseline = task["instance"], task["intervention"], task["baseline"]
            numeric = mode in ("public_numeric", "public_both")
            expanded = mode in ("public_time", "public_both")
            cache = {}
            corridors = {c["corridor_id"]: c for c in instance["topology"]["corridors"]}
            fleet = {u["uav_id"]: u for u in instance["fleet"]}

            def options(inst, inter, mission, *args, **kwargs):
                mid = mission["mission_id"]
                if mid not in cache:
                    source = inst
                    if expanded:
                        source = dict(inst)
                        max_travel = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
                        source["horizon_slots"] = inst["horizon_slots"] + max_travel + inst["turnaround_slots"] + inst["max_charge_blocks"]
                    opts = original_options(source, inter, mission, *args, **kwargs)
                    if expanded:
                        opts = [o for o in opts if o["depart_slot"] < inst["horizon_slots"]]
                    if numeric:
                        path_map = {p["path_id"]: p for p in mission["path_options"]}
                        uav = fleet[mission["uav_id"]]
                        incoming = mission.get("incoming_deadhead")
                        for option in opts:
                            option["energy_kwh_stored"] = option["energy_kwh"]
                            option["energy_kwh"] = exact_energy(path_map[option["path_id"]], mission, uav, corridors) + (exact_energy(incoming, mission, uav, corridors, True) if incoming else 0)
                    cache[mid] = opts
                return cache[mid]

            def feasible(inst, mission, option, uav_state, calendars, maps):
                if not numeric:
                    return original_feasible(inst, mission, option, uav_state, calendars, maps)
                # The archived function checks the same resources; expose the
                # public verifier's 1e-6 kWh boundary without changing its order.
                state = uav_state[mission["uav_id"]]
                fleet_row = maps["fleet"][mission["uav_id"]]
                if option["deadhead_start_slot"] < state["clock"]:
                    return False
                corridor, pad, charger = policy.option_events(mission, option)
                resources = inst["resources"]
                if not policy.capacity_ok(calendars["corridor"], corridor, resources["corridor_capacity_by_slot_default"], maps["corridor_override"]):
                    return False
                if not policy.capacity_ok(calendars["pad"], pad, resources["pad_capacity_by_slot_default"], maps["pad_override"]):
                    return False
                if not policy.capacity_ok(calendars["charger"], charger, resources["charger_capacity_by_slot_default"], maps["charger_override"]):
                    return False
                after_flight = state["soc"] - option["energy_kwh"]
                after_charge = after_flight + option["charge_energy_kwh"]
                return after_flight >= fleet_row["reserve_kwh"] - 1e-6 and after_charge <= fleet_row["battery_capacity_kwh"] + 1e-6

            def priority(option, base, mission, slot_min):
                if not numeric:
                    return original_priority(option, base, mission, slot_min)
                copy_option = dict(option, energy_kwh=option["energy_kwh_stored"])
                return original_priority(copy_option, base, mission, slot_min)

            core.candidate_options = options
            policy.feasible_option = feasible
            policy.local_priority = priority
            start = time.perf_counter()
            decisions, telemetry = policy.construct(instance, intervention, baseline, core)
            elapsed = time.perf_counter() - start
            task_times.append(elapsed)
            rid = task["record_id"]
            decisions_by_mode[mode][rid] = decisions
            public_row = {"record_id": rid, "raw_text": json.dumps({"record_id": rid, "decisions": decisions}, separators=(",", ":"))}
            out_rows.append(public_row)
            private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
            scored[rid] = scorer.score_one(rid, public_row["raw_text"], private, core, mods["formal"], bridge, mods)
            if index % 12 == 0:
                print(mode, index, "elapsed", round(sum(task_times), 1), flush=True)
        core.candidate_options = original_options
        policy.feasible_option = original_feasible
        policy.local_priority = original_priority
        score_by_mode[mode] = scored
        timings[mode] = {"sum_sec": sum(task_times), "mean_sec": statistics.mean(task_times), "median_sec": statistics.median(task_times), "per_task_sec": dict(zip((t["record_id"] for t in tasks), task_times))}
        with (output / f"{mode}.jsonl").open("w", encoding="utf-8") as handle:
            for row in out_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary[mode] = {"admissible": sum(r["schema_valid"] and r["formal_feasible"] for r in scored.values()), "reference_quality": sum(r["formal_feasible"] and r["oracle_equivalent"] for r in scored.values()), "served_total": sum(not d["held"] for ds in decisions_by_mode[mode].values() for d in ds), "changed_from_archived_outputs": sum(decisions_by_mode[mode][rid] != archived[rid] for rid in archived)}
    (output / "summary.json").write_text(json.dumps({"summary": summary, "timings": timings}, indent=2) + "\n", encoding="utf-8")
    detail = []
    for task in tasks:
        rid = task["record_id"]
        if decisions_by_mode["public_both"][rid] == archived[rid]:
            continue
        row = {"record_id": rid}
        for mode in decisions_by_mode:
            row[mode + "_decisions"] = decisions_by_mode[mode][rid]
            row[mode + "_objective"] = score_by_mode[mode][rid]["objective_vector"]
            row[mode + "_quality"] = score_by_mode[mode][rid]["formal_feasible"] and score_by_mode[mode][rid]["oracle_equivalent"]
        detail.append(row)
    (output / "changed_tasks.json").write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
