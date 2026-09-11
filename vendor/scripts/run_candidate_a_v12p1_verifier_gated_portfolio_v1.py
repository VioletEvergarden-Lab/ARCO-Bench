#!/usr/bin/env python3
"""Freeze and run oracle-free two-source Candidate A portfolio selectors."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


VERSION = "candidate_a_v12p1_verifier_gated_two_source_portfolio_v1"
MODELS = ("deepseek", "qwen", "luna")
ROOT_KEYS = {"record_id", "decisions"}
DECISION_KEYS = {"mission_id", "uav_id", "held", "path_id", "depart_slot", "charge_blocks"}
TIERS = ("urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh")
ENERGY_TOL = 1e-4


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_obj(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime(repo: Path) -> tuple[Any, Any]:
    runner = load_module("portfolio_runtime_loader", repo / "scripts" / "integrated_repair_candidate_a_v12_multitemplate_structural_successor_v1.py")
    _, _, modules = runner.load_runtime(repo, "portfolio_operational_runtime")
    return modules["core"], modules["formal"]


def parse_public(raw_text: str, task: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        root = json.loads(raw_text)
    except Exception as exc:
        return None, [f"JSON_PARSE:{type(exc).__name__}"]
    if not isinstance(root, dict) or set(root) != ROOT_KEYS:
        return None, ["ROOT_FIELDS_MISMATCH"]
    if root.get("record_id") != task["record_id"]:
        errors.append("RECORD_ID_MISMATCH")
    decisions = root.get("decisions")
    if not isinstance(decisions, list):
        return None, errors + ["DECISIONS_NOT_LIST"]
    missions = {m["mission_id"]: m for m in task["instance"]["missions"]}
    seen: set[str] = set()
    normalized = []
    for position, row in enumerate(decisions):
        prefix = f"DECISION_{position}:"
        if not isinstance(row, dict) or set(row) != DECISION_KEYS:
            errors.append(prefix + "FIELDS_MISMATCH")
            continue
        mission_id = row.get("mission_id")
        if not isinstance(mission_id, str) or mission_id not in missions:
            errors.append(prefix + "MISSION_ID_INVALID")
            continue
        if mission_id in seen:
            errors.append(prefix + "MISSION_DUPLICATE")
            continue
        seen.add(mission_id)
        mission = missions[mission_id]
        if row.get("uav_id") != mission["uav_id"]:
            errors.append(prefix + "UAV_ID_INVALID")
        held = row.get("held")
        charge = row.get("charge_blocks")
        depart = row.get("depart_slot")
        path_id = row.get("path_id")
        if type(held) is not bool:
            errors.append(prefix + "HELD_NOT_BOOLEAN")
            continue
        if type(charge) is not int or not 0 <= charge <= int(task["instance"]["max_charge_blocks"]):
            errors.append(prefix + "CHARGE_BLOCKS_INVALID")
        if held:
            if path_id is not None or depart is not None or charge != 0:
                errors.append(prefix + "HELD_FIELDS_INVALID")
        else:
            allowed_paths = {path["path_id"] for path in mission["path_options"]}
            if path_id not in allowed_paths:
                errors.append(prefix + "PATH_ID_INVALID")
            if type(depart) is not int or not 0 <= depart < int(task["instance"]["horizon_slots"]):
                errors.append(prefix + "DEPART_SLOT_INVALID")
        normalized.append({key: row[key] for key in ("mission_id", "uav_id", "held", "path_id", "depart_slot", "charge_blocks")})
    if seen != set(missions) or len(decisions) != len(missions):
        errors.append("MISSION_COVERAGE_MISMATCH")
    return ({"record_id": task["record_id"], "decisions": normalized} if not errors else None), errors


def public_evaluate(parsed: dict[str, Any] | None, errors: list[str], task: dict[str, Any], formal: Any) -> dict[str, Any]:
    base = {"schema_valid": parsed is not None and not errors, "parse_errors": errors, "formal_feasible": False, "formal_error_codes": [], "objective_vector": None}
    if parsed is None:
        return base
    instance = copy.deepcopy(task["instance"])
    instance["model_version"] = formal.EXPECTED_MODEL_VERSION
    instance["instance_sha256"] = sha_obj(instance)
    plan = {
        "artifact_flags": sorted(formal.FLAGS), "model_version": f"deterministic_selector::{VERSION}",
        "instance_id": instance["instance_id"], "instance_sha256": instance["instance_sha256"],
        "intervention_sha256": task["intervention"].get("intervention_sha256"),
        "status": "CANDIDATE", "decisions": parsed["decisions"],
    }
    evaluated = formal.evaluate_submission(instance, task["intervention"], plan, baseline=task["baseline"], oracle=None)
    return {
        **base, "formal_feasible": bool(evaluated["valid"]),
        "formal_error_codes": [item["code"] for item in evaluated.get("errors", [])],
        "objective_vector": evaluated.get("objective"),
    }


def lex_compare(left: dict[str, float], right: dict[str, float]) -> int:
    for name in TIERS:
        a, b = float(left[name]), float(right[name])
        if name == "energy_kwh" and abs(a - b) <= ENERGY_TOL:
            continue
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


def freeze(repo: Path, phase: Path, main: Path, baseline_phase: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    index_path = phase / "public" / "CORE_72.json"
    spec = {
        "version": VERSION, "date_frozen": "2026-08-14",
        "scientific_role": "POST_FREEZE_SECONDARY_SYSTEM_COMPOSITION_ANALYSIS",
        "portfolios": [f"resource_aware_greedy+{model}" for model in MODELS],
        "operational_admission": "public schema valid AND public formal verifier feasible",
        "mechanism_semantics_during_selection": False,
        "mechanism_semantics_reason": "requires private selected_pair and mechanism metadata; offline evaluation only",
        "comparison": list(TIERS), "energy_equality_tolerance_kwh": ENERGY_TOL,
        "tie_break": "resource_aware_greedy",
        "both_inadmissible": "canonical selector failure; no synthesized repair",
        "oracle_access": False, "private_evaluator_access": False, "outcome_label_access": False,
        "source_sha256": sha_file(Path(__file__).resolve()),
        "core72_index_sha256": sha_file(index_path),
        "baseline_responses_sha256": sha_file(baseline_phase / "BASELINE_RESPONSES.jsonl"),
        "model_scoring_input_sha256": {model: sha_file(main / "scoring_inputs" / f"{model}.jsonl") for model in MODELS},
        "record_count": 72,
    }
    write_json(output / "FROZEN_SELECTOR_SPECIFICATION.json", spec)
    index = read_json(index_path)
    with (output / "FROZEN_SELECTOR_REGISTRY.jsonl").open("w", encoding="utf-8") as handle:
        for rank, entry in enumerate(index["records"], start=1):
            handle.write(canonical({"rank": rank, "record_id": entry["record_id"], "public_task_sha256": entry["sha256"]}) + "\n")
    write_json(output / "PREEXECUTION_VALIDATION_RESULTS.json", {
        "status": "VERIFIER_GATED_PORTFOLIO_FROZEN_READY_FOR_OFFLINE_EXECUTION",
        "checks": {"core72_count_72": index["count"] == 72, "unique_ids": len({x["record_id"] for x in index["records"]}) == 72, "three_two_source_portfolios": len(MODELS) == 3},
    })


def run(repo: Path, phase: Path, main: Path, baseline_phase: Path, output: Path) -> None:
    spec = read_json(output / "FROZEN_SELECTOR_SPECIFICATION.json")
    if spec["source_sha256"] != sha_file(Path(__file__).resolve()):
        raise RuntimeError("FROZEN_SELECTOR_SOURCE_HASH_MISMATCH")
    if (output / "RUN_COMPLETE.json").exists():
        raise RuntimeError("PORTFOLIO_ALREADY_COMPLETED")
    core, formal = load_runtime(repo)
    del core
    index = read_json(phase / "public" / "CORE_72.json")
    baseline_inputs = {row["record_id"]: row["raw_text"] for row in read_jsonl(baseline_phase / "BASELINE_RESPONSES.jsonl")}
    model_inputs = {model: {row["record_id"]: row.get("raw_text", "") for row in read_jsonl(main / "scoring_inputs" / f"{model}.jsonl")} for model in MODELS}
    outputs = {model: (output / f"PORTFOLIO_RESPONSES_{model}.jsonl").open("x", encoding="utf-8") for model in MODELS}
    traces = {model: (output / f"PORTFOLIO_TRACE_{model}.jsonl").open("x", encoding="utf-8") for model in MODELS}
    started = time.perf_counter()
    try:
        for rank, entry in enumerate(index["records"], start=1):
            task = read_json(phase / entry["path"])
            record_id = entry["record_id"]
            candidates = {"resource_aware_greedy": baseline_inputs[record_id]}
            for model in MODELS:
                candidates[model] = model_inputs[model][record_id]
                selection_start = time.perf_counter()
                evaluations: dict[str, dict[str, Any]] = {}
                parsed_payloads: dict[str, dict[str, Any] | None] = {}
                for source in ("resource_aware_greedy", model):
                    parsed, errors = parse_public(candidates[source], task)
                    parsed_payloads[source] = parsed
                    evaluations[source] = public_evaluate(parsed, errors, task, formal)
                    evaluations[source]["admitted"] = bool(evaluations[source]["schema_valid"] and evaluations[source]["formal_feasible"])
                baseline_admitted = evaluations["resource_aware_greedy"]["admitted"]
                model_admitted = evaluations[model]["admitted"]
                tie = False
                if not baseline_admitted and not model_admitted:
                    selected_source, reason, selected_raw = None, "BOTH_INADMISSIBLE", ""
                elif baseline_admitted and not model_admitted:
                    selected_source, reason, selected_raw = "resource_aware_greedy", "ONLY_POLICY_ADMITTED", candidates["resource_aware_greedy"]
                elif model_admitted and not baseline_admitted:
                    selected_source, reason, selected_raw = model, "ONLY_MODEL_ADMITTED", candidates[model]
                else:
                    comparison = lex_compare(evaluations["resource_aware_greedy"]["objective_vector"], evaluations[model]["objective_vector"])
                    if comparison < 0:
                        selected_source, reason, selected_raw = "resource_aware_greedy", "POLICY_LEXICOGRAPHICALLY_BETTER", candidates["resource_aware_greedy"]
                    elif comparison > 0:
                        selected_source, reason, selected_raw = model, "MODEL_LEXICOGRAPHICALLY_BETTER", candidates[model]
                    else:
                        selected_source, reason, selected_raw, tie = "resource_aware_greedy", "OBJECTIVE_TIE_POLICY_FIRST", candidates["resource_aware_greedy"], True
                runtime = time.perf_counter() - selection_start
                outputs[model].write(canonical({"record_id": record_id, "raw_text": selected_raw}) + "\n")
                traces[model].write(canonical({
                    "rank": rank, "record_id": record_id, "portfolio": f"resource_aware_greedy+{model}",
                    "candidates": evaluations, "selected_source": selected_source, "selection_reason": reason,
                    "tie_break_triggered": tie, "selector_runtime_sec": round(runtime, 9),
                    "selected_response_sha256": hashlib.sha256(selected_raw.encode("utf-8")).hexdigest(),
                }) + "\n")
    finally:
        for handle in outputs.values():
            handle.close()
        for handle in traces.values():
            handle.close()
    elapsed = time.perf_counter() - started
    write_json(output / "RUN_COMPLETE.json", {
        "version": VERSION, "status": "VERIFIER_GATED_PORTFOLIO_OFFLINE_EXECUTION_COMPLETED",
        "portfolios": 3, "records_per_portfolio": 72, "selections_per_portfolio_record": 1,
        "wall_runtime_sec": round(elapsed, 9),
        "response_sha256": {model: sha_file(output / f"PORTFOLIO_RESPONSES_{model}.jsonl") for model in MODELS},
        "trace_sha256": {model: sha_file(output / f"PORTFOLIO_TRACE_{model}.jsonl") for model in MODELS},
    })


def self_test(repo: Path, phase: Path, main: Path, baseline_phase: Path) -> None:
    _, formal = load_runtime(repo)
    index = read_json(phase / "public" / "CORE_72.json")
    task = read_json(phase / index["records"][0]["path"])
    baseline_raw = read_jsonl(baseline_phase / "BASELINE_RESPONSES.jsonl")[0]["raw_text"]
    model_raw = read_jsonl(main / "scoring_inputs" / "deepseek.jsonl")[0]["raw_text"]
    checks = []
    for raw in (baseline_raw, model_raw):
        parsed, errors = parse_public(raw, task)
        checks.append(public_evaluate(parsed, errors, task, formal))
    assert checks[0]["formal_feasible"]
    assert checks[0]["objective_vector"] is not None
    print(canonical({"status": "SELF_TEST_PASSED", "record_id": task["record_id"], "candidate_formal": [x["formal_feasible"] for x in checks]}))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("self-test", "freeze", "run"):
        child = sub.add_parser(command)
        child.add_argument("--repo", required=True)
        child.add_argument("--phase", required=True)
        child.add_argument("--main", required=True)
        child.add_argument("--baseline-phase", required=True)
        if command != "self-test":
            child.add_argument("--output", required=True)
    args = parser.parse_args()
    repo, phase, main_phase, baseline_phase = map(lambda x: Path(x).resolve(), (args.repo, args.phase, args.main, args.baseline_phase))
    if args.command == "self-test":
        self_test(repo, phase, main_phase, baseline_phase)
    elif args.command == "freeze":
        freeze(repo, phase, main_phase, baseline_phase, Path(args.output).resolve())
    else:
        run(repo, phase, main_phase, baseline_phase, Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
