#!/usr/bin/env python3
"""Freeze and run the Candidate A resource-aware operational greedy baseline.

The generator reads only the frozen public Core-72 index and records.  It never
reads evaluator records, oracle plans, model outputs, or scorer conclusions.
Core-72 execution is guarded as a one-shot run after a source/spec freeze.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


VERSION = "candidate_a_v12p1_resource_aware_sequential_greedy_v1"
FINAL_STATUS = "RESOURCE_AWARE_GREEDY_CORE72_ONE_SHOT_COMPLETED"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def held_decision(mission: dict[str, Any]) -> dict[str, Any]:
    return {
        "mission_id": mission["mission_id"], "uav_id": mission["uav_id"],
        "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0,
    }


def served_decision(mission: dict[str, Any], option: dict[str, Any]) -> dict[str, Any]:
    return {
        "mission_id": mission["mission_id"], "uav_id": mission["uav_id"],
        "held": False, "path_id": option["path_id"],
        "depart_slot": int(option["depart_slot"]), "charge_blocks": int(option["charge_blocks"]),
    }


def option_events(mission: dict[str, Any], option: dict[str, Any]) -> tuple[Counter, Counter, Counter]:
    corridor = Counter(option["service_occupancy"] + option["deadhead_occupancy"])
    pad: Counter = Counter()
    incoming = mission.get("incoming_deadhead")
    if incoming:
        pad[(incoming["node_sequence"][0], option["deadhead_start_slot"])] += 1
        pad[(mission["origin_vertiport"], option["deadhead_arrival_slot"])] += 1
    pad[(mission["origin_vertiport"], option["depart_slot"])] += 1
    pad[(mission["destination_vertiport"], option["arrival_slot"])] += 1
    charger: Counter = Counter()
    for slot in range(option["charge_start_slot"], option["charge_start_slot"] + option["charge_blocks"]):
        charger[(mission["destination_vertiport"], slot)] += 1
    return corridor, pad, charger


def capacity_ok(current: Counter, added: Counter, default: dict[str, int], override: dict[tuple[str, int], int]) -> bool:
    return all(current[key] + amount <= override.get(key, int(default[key[0]])) for key, amount in added.items())


def feasible_option(
    instance: dict[str, Any], mission: dict[str, Any], option: dict[str, Any],
    uav_state: dict[str, dict[str, float]], calendars: dict[str, Counter],
    resource_maps: dict[str, Any],
) -> bool:
    uav_id = mission["uav_id"]
    fleet = resource_maps["fleet"][uav_id]
    state = uav_state[uav_id]
    if option["deadhead_start_slot"] < state["clock"]:
        return False
    corridor, pad, charger = option_events(mission, option)
    resources = instance["resources"]
    if not capacity_ok(calendars["corridor"], corridor, resources["corridor_capacity_by_slot_default"], resource_maps["corridor_override"]):
        return False
    if not capacity_ok(calendars["pad"], pad, resources["pad_capacity_by_slot_default"], resource_maps["pad_override"]):
        return False
    if not capacity_ok(calendars["charger"], charger, resources["charger_capacity_by_slot_default"], resource_maps["charger_override"]):
        return False
    soc_before_charge = state["soc"] - float(option["energy_kwh"])
    if soc_before_charge < float(fleet["reserve_kwh"]) - 1e-9:
        return False
    soc_after_charge = soc_before_charge + float(option["charge_energy_kwh"])
    if soc_after_charge > float(fleet["battery_capacity_kwh"]) + 1e-9:
        return False
    return True


def apply_option(
    mission: dict[str, Any], option: dict[str, Any],
    uav_state: dict[str, dict[str, float]], calendars: dict[str, Counter],
) -> None:
    corridor, pad, charger = option_events(mission, option)
    calendars["corridor"].update(corridor)
    calendars["pad"].update(pad)
    calendars["charger"].update(charger)
    state = uav_state[mission["uav_id"]]
    state["soc"] = state["soc"] - float(option["energy_kwh"]) + float(option["charge_energy_kwh"])
    state["clock"] = int(option["charge_start_slot"] + option["charge_blocks"])


def clone_state(uav_state: dict[str, dict[str, float]], calendars: dict[str, Counter]) -> tuple[dict[str, dict[str, float]], dict[str, Counter]]:
    return copy.deepcopy(uav_state), {name: Counter(values) for name, values in calendars.items()}


def local_priority(option: dict[str, Any], baseline_entry: dict[str, Any], mission: dict[str, Any], slot_min: int) -> tuple[Any, ...]:
    base_charge = int(baseline_entry.get("charge_blocks") or 0)
    base_depart = int(baseline_entry.get("depart_slot") or 0)
    repair = 20 * int(option["path_id"] != baseline_entry.get("path_id"))
    repair += abs(int(option["depart_slot"]) - base_depart)
    repair += 10 * int((int(option["charge_blocks"]) > 0) != (base_charge > 0))
    repair += 2 * abs(int(option["charge_blocks"]) - base_charge)
    tardiness = int(option["tardiness_slots"]) * slot_min * (10 if mission.get("priority") == "urgent" else 1)
    delay_charge = (int(option["delay_slots"]) + int(option["charge_blocks"])) * slot_min
    return (
        repair, tardiness, delay_charge, round(float(option["energy_kwh"]), 8),
        int(option["depart_slot"]), str(option["path_id"]), int(option["charge_blocks"]),
    )


def build_resource_maps(instance: dict[str, Any], intervention: dict[str, Any], core: Any) -> dict[str, Any]:
    _, _, initial_soc, _, corridor_override, pad_override, charger_override = core.effective_maps(instance, intervention)
    return {
        "fleet": {u["uav_id"]: u for u in instance["fleet"]},
        "initial_soc": initial_soc,
        "corridor_override": corridor_override,
        "pad_override": pad_override,
        "charger_override": charger_override,
    }


def construct(instance: dict[str, Any], intervention: dict[str, Any], baseline: dict[str, Any], core: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = time.perf_counter()
    missions = {m["mission_id"]: m for m in instance["missions"]}
    baseline_map = {d["mission_id"]: d for d in baseline["decisions"]}
    by_uav: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mission in instance["missions"]:
        by_uav[mission["uav_id"]].append(mission)
    for sequence in by_uav.values():
        sequence.sort(key=lambda m: (int(m["sequence_index"]), m["mission_id"]))
    resource_maps = build_resource_maps(instance, intervention, core)
    uav_state = {
        uav_id: {"clock": int(resource_maps["fleet"][uav_id]["available_slot"]), "soc": float(resource_maps["initial_soc"][uav_id])}
        for uav_id in sorted(by_uav)
    }
    calendars = {"corridor": Counter(), "pad": Counter(), "charger": Counter()}
    heads = {uav_id: 0 for uav_id in by_uav}
    suffix_held = {uav_id: False for uav_id in by_uav}
    decisions: dict[str, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = []
    candidates_considered = 0
    lookahead_checks = 0
    release, _, _, _, _, _, _ = core.effective_maps(instance, intervention)

    while any(heads[uav_id] < len(by_uav[uav_id]) for uav_id in heads):
        eligible = []
        for uav_id, sequence in by_uav.items():
            index = heads[uav_id]
            if index >= len(sequence):
                continue
            remaining = sequence[index:]
            urgent_remaining = sum(m.get("priority") == "urgent" for m in remaining)
            mission = sequence[index]
            base_depart = baseline_map[mission["mission_id"]].get("depart_slot")
            eligible.append((
                -urgent_remaining, int(release[mission["mission_id"]]),
                int(base_depart if base_depart is not None else instance["horizon_slots"]),
                uav_id, int(mission["sequence_index"]), mission["mission_id"], mission,
            ))
        *_, mission = min(eligible)
        uav_id = mission["uav_id"]
        index = heads[uav_id]
        if suffix_held[uav_id]:
            decisions[mission["mission_id"]] = held_decision(mission)
            trace.append({"mission_id": mission["mission_id"], "terminal": "SUFFIX_HOLD_PROPAGATED"})
            heads[uav_id] += 1
            continue

        all_options = core.candidate_options(instance, intervention, mission)
        feasible = [o for o in all_options if feasible_option(instance, mission, o, uav_state, calendars, resource_maps)]
        candidates_considered += len(all_options)
        next_mission = by_uav[uav_id][index + 1] if index + 1 < len(by_uav[uav_id]) else None
        ranked = []
        for option in feasible:
            next_serviceable = True
            if next_mission is not None:
                lookahead_checks += 1
                sim_state, sim_calendars = clone_state(uav_state, calendars)
                apply_option(mission, option, sim_state, sim_calendars)
                next_options = core.candidate_options(instance, intervention, next_mission)
                next_serviceable = any(feasible_option(instance, next_mission, candidate, sim_state, sim_calendars, resource_maps) for candidate in next_options)
            ranked.append(((0 if next_serviceable else 1, *local_priority(option, baseline_map[mission["mission_id"]], mission, int(instance["slot_min"]))), option, next_serviceable))

        if not ranked:
            suffix_held[uav_id] = True
            decisions[mission["mission_id"]] = held_decision(mission)
            trace.append({
                "mission_id": mission["mission_id"], "terminal": "NO_RESOURCE_SOC_TIME_FEASIBLE_OPTION_SUFFIX_HELD",
                "enumerated_options": len(all_options), "feasible_options": 0,
            })
        else:
            ranked.sort(key=lambda item: item[0])
            key, chosen, next_serviceable = ranked[0]
            decisions[mission["mission_id"]] = served_decision(mission, chosen)
            apply_option(mission, chosen, uav_state, calendars)
            trace.append({
                "mission_id": mission["mission_id"], "terminal": "SERVED",
                "enumerated_options": len(all_options), "feasible_options": len(feasible),
                "next_mission_serviceable": next_serviceable, "selection_key": list(key),
                "chosen": served_decision(mission, chosen),
                "post_soc_kwh": round(uav_state[uav_id]["soc"], 6), "post_clock_slot": int(uav_state[uav_id]["clock"]),
            })
        heads[uav_id] += 1

    ordered = [decisions[m["mission_id"]] for m in instance["missions"]]
    telemetry = {
        "algorithm": VERSION, "runtime_sec": round(time.perf_counter() - start, 9),
        "candidates_considered": candidates_considered, "one_step_lookahead_checks": lookahead_checks,
        "served": sum(not d["held"] for d in ordered), "held": sum(d["held"] for d in ordered),
        "trace": trace,
    }
    return ordered, telemetry


def public_records(phase: Path) -> list[tuple[dict[str, Any], Path]]:
    index_path = phase / "public" / "CORE_72.json"
    index = read_json(index_path)
    rows = []
    for entry in index["records"]:
        path = phase / entry["path"]
        rows.append((read_json(path), path))
    if len(rows) != 72:
        raise RuntimeError(f"CORE72_COUNT_MISMATCH:{len(rows)}")
    return rows


def freeze(repo: Path, phase: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve()
    rows = public_records(phase)
    index_path = phase / "public" / "CORE_72.json"
    registry = [
        {
            "rank": rank, "record_id": record["record_id"],
            "path": str(path.relative_to(phase)).replace("\\", "/"),
            "canonical_sha256": sha256_bytes(canonical(record).encode("utf-8")),
            "raw_file_sha256": sha256_file(path),
        }
        for rank, (record, path) in enumerate(rows, start=1)
    ]
    spec = {
        "version": VERSION,
        "date_frozen": "2026-08-14",
        "scientific_role": "DETERMINISTIC_RESOURCE_AWARE_SIMPLE_OPERATIONAL_POLICY_BASELINE",
        "input_boundary": "FROZEN_PUBLIC_CORE72_ONLY",
        "forbidden_inputs": ["private evaluator records", "oracle solutions", "hidden labels", "model outputs", "scorer conclusions"],
        "fixed_skeleton": ["mission-to-UAV assignment", "per-UAV sequence", "incoming deadhead path"],
        "allowed_actions": ["suffix hold", "path choice", "departure slot", "post-service charge blocks"],
        "state": ["per-UAV clock", "per-UAV SOC", "corridor calendar", "pad calendar", "charger calendar"],
        "mission_chain_priority": "descending count of urgent missions in remaining fixed suffix, then effective release, baseline departure, UAV ID, sequence index, mission ID",
        "candidate_priority": "one-step next-mission serviceability, then exact local L3 repair burden, L4 weighted tardiness, L5 delay-plus-charge wait, L6 service-plus-deadhead energy, deterministic IDs",
        "lookahead": "one immediate next mission on same UAV; feasibility existence only",
        "failure_rule": "if no feasible option exists, hold current and all later missions on that UAV",
        "solver_or_verifier_during_generation": False,
        "outcome_adaptive_tuning": False,
        "core72_runs_per_record": 1,
        "source_sha256": sha256_file(source),
        "core72_index_sha256": sha256_file(index_path),
        "record_count": len(registry),
    }
    write_json(output / "FROZEN_BASELINE_SPECIFICATION.json", spec)
    with (output / "FROZEN_CORE72_REGISTRY.jsonl").open("w", encoding="utf-8") as handle:
        for row in registry:
            handle.write(canonical(row) + "\n")
    write_json(output / "PREEXECUTION_VALIDATION_RESULTS.json", {
        "status": "RESOURCE_AWARE_GREEDY_FROZEN_READY_FOR_ONE_SHOT_CORE72",
        "checks": {
            "core72_count_72": len(registry) == 72,
            "unique_record_ids": len({x["record_id"] for x in registry}) == 72,
            "all_public_canonical_hashes_match_index": all(x["canonical_sha256"] == read_json(index_path)["records"][x["rank"] - 1]["sha256"] for x in registry),
            "generator_source_frozen": True,
        },
    })


def run(repo: Path, phase: Path, output: Path) -> None:
    spec_path = output / "FROZEN_BASELINE_SPECIFICATION.json"
    if not spec_path.exists():
        raise RuntimeError("BASELINE_NOT_FROZEN")
    for forbidden in ("RUN_COMPLETE.json", "BASELINE_RESPONSES.jsonl", "BASELINE_TRACE.jsonl"):
        if (output / forbidden).exists():
            raise RuntimeError("ONE_SHOT_CORE72_ALREADY_STARTED_OR_COMPLETED")
    spec = read_json(spec_path)
    if spec["source_sha256"] != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("FROZEN_GENERATOR_SOURCE_HASH_MISMATCH")
    index_path = phase / "public" / "CORE_72.json"
    if spec["core72_index_sha256"] != sha256_file(index_path):
        raise RuntimeError("FROZEN_CORE72_INDEX_HASH_MISMATCH")
    core = load_module("candidate_a_operational_baseline_core", repo / "scripts" / "integrated_repair_phase_minus1d_core_v1.py")
    rows = public_records(phase)
    responses_path = output / "BASELINE_RESPONSES.jsonl"
    trace_path = output / "BASELINE_TRACE.jsonl"
    decisions_path = output / "BASELINE_DECISIONS.jsonl"
    started = time.time()
    total_runtime = 0.0
    with responses_path.open("x", encoding="utf-8") as responses, trace_path.open("x", encoding="utf-8") as traces, decisions_path.open("x", encoding="utf-8") as decisions_handle:
        for rank, (record, _) in enumerate(rows, start=1):
            result, telemetry = construct(record["instance"], record["intervention"], record["baseline"], core)
            total_runtime += telemetry["runtime_sec"]
            payload = {"record_id": record["record_id"], "decisions": result}
            raw_text = canonical(payload)
            responses.write(canonical({"record_id": record["record_id"], "raw_text": raw_text}) + "\n")
            decisions_handle.write(canonical(payload) + "\n")
            traces.write(canonical({"rank": rank, "record_id": record["record_id"], **telemetry}) + "\n")
    completed = time.time()
    write_json(output / "RUN_COMPLETE.json", {
        "version": VERSION, "status": FINAL_STATUS, "record_count": len(rows),
        "formal_generations_per_record": 1, "started_unix": started, "completed_unix": completed,
        "wall_runtime_sec": round(completed - started, 9), "sum_record_runtime_sec": round(total_runtime, 9),
        "responses_sha256": sha256_file(responses_path), "trace_sha256": sha256_file(trace_path),
        "decisions_sha256": sha256_file(decisions_path),
    })


def self_test(repo: Path) -> None:
    core = load_module("candidate_a_operational_baseline_core_selftest", repo / "scripts" / "integrated_repair_phase_minus1d_core_v1.py")
    phase = repo / "analysis" / "integrated_repair_candidate_a_v12_curated_repair_track_freeze_v1"
    record, _ = public_records(phase)[0]
    first, trace1 = construct(record["instance"], record["intervention"], record["baseline"], core)
    second, trace2 = construct(record["instance"], record["intervention"], record["baseline"], core)
    assert canonical(first) == canonical(second)
    assert len(first) == len(record["instance"]["missions"])
    assert trace1["served"] + trace1["held"] == len(first)
    assert trace2["algorithm"] == VERSION
    print(canonical({"status": "SELF_TEST_PASSED", "record_id": record["record_id"], "served": trace1["served"], "held": trace1["held"]}))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("self-test", "freeze", "run"):
        child = sub.add_parser(command)
        child.add_argument("--repo", required=True)
        if command != "self-test":
            child.add_argument("--phase", required=True)
            child.add_argument("--output", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    if args.command == "self-test":
        self_test(repo)
    elif args.command == "freeze":
        freeze(repo, Path(args.phase).resolve(), Path(args.output).resolve())
    else:
        run(repo, Path(args.phase).resolve(), Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
