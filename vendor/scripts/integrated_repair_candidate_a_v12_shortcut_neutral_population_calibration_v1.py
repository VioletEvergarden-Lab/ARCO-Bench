#!/usr/bin/env python3
"""Shortcut-neutral fixed-denominator development population calibration.

This module overlays a label-independent nuisance library on the accepted V3
coupled certificate constructor.  It does not change the mathematical core,
mechanism predicates, objective dictionary, verifier, V4, or parent-success
contract.  Registered attempts consume a fixed opportunity budget and retain
their outcome even when no candidate is admitted.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VERSION = "candidate_a_v12_shortcut_neutral_population_calibration_v1"
EVIDENCE_SCOPE = "DEVELOPMENT_ONLY_NOT_FORMAL_CONFIRMATION_NOT_MODEL_EVIDENCE"
PROFILE_TIME_SHIFTS = (0, 2, 4, 6, 1, 3, 5, 7)
EXPECTED_ATTEMPTS = 96


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_LOAD_FAILED:" + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_bridge(repo: Path, module_name: str = "candidate_a_calibration_bridge_v3") -> Any:
    return load(module_name, repo / "scripts" / "integrated_repair_candidate_a_v12_coupled_certificate_first_bridge_v3.py")


def _rehash_cell(bridge: Any, modules: dict[str, Any], cell: dict[str, Any], attempt: dict[str, Any], candidate_variant: int) -> None:
    core = modules["core"]
    instance = cell["instance"]
    instance_id = "calv1_" + hashlib.sha256(
        f"{attempt['attempt_id']}|{candidate_variant}|{attempt['nuisance_profile']}".encode()
    ).hexdigest()[:24]
    instance["instance_id"] = instance_id
    # Public provenance contains no mechanism, role, template/profile ID, witness,
    # target/competitor identity, or constructor branch.
    instance["provenance"] = {
        "generator_version": VERSION,
        "evidence_scope": EVIDENCE_SCOPE,
        "mixed_fleet": True,
        "prospective_fixed_denominator": True,
    }
    instance["structural_signatures"] = core.structural_signatures(instance)
    instance.pop("instance_sha256", None)
    instance["instance_sha256"] = core.sha256_obj(instance)
    empty = core.empty_intervention(instance)
    empty["intervention_sha256"] = core.sha256_obj(empty)
    decisions = copy.deepcopy(cell["baseline"]["decisions"])
    baseline = core.make_plan(instance, empty, "calibration_preintervention_baseline", decisions)
    intervention = cell["intervention"]
    intervention["instance_id"] = instance_id
    intervention["baseline_plan_sha256"] = baseline["plan_sha256"]
    intervention.pop("intervention_sha256", None)
    intervention["intervention_sha256"] = core.sha256_obj(intervention)
    cell["private_cell_id"] = instance_id
    cell["baseline"] = baseline
    cell["intervention"] = intervention
    cell["calibration_private_lineage"] = {
        "attempt_id": attempt["attempt_id"],
        "attempt_rank": attempt["rank"],
        "ancestor_id": attempt["ancestor_id"],
        "nuisance_profile": attempt["nuisance_profile"],
        "candidate_variant": candidate_variant,
        "template_family": attempt["template_family"],
    }


def _apply_label_independent_time_translation(bridge: Any, cell: dict[str, Any], profile_index: int) -> None:
    """Apply an exact common time translation to the complete construction.

    Release, due, baseline departures, availability, closures and the horizon
    move together.  Relative time, feasibility and every objective difference
    are unchanged.  Each label receives every translation exactly once.
    """
    shift = int(PROFILE_TIME_SHIFTS[profile_index])
    if shift == 0:
        return
    instance = cell["instance"]
    instance["horizon_slots"] = int(instance["horizon_slots"]) + shift
    for fleet in instance["fleet"]:
        fleet["available_slot"] = int(fleet.get("available_slot", 0)) + shift
    for mission in instance["missions"]:
        mission["release_slot"] = int(mission["release_slot"]) + shift
        mission["due_slot"] = int(mission["due_slot"]) + shift
    for decision in cell["baseline"]["decisions"]:
        if decision.get("depart_slot") is not None:
            decision["depart_slot"] = int(decision["depart_slot"]) + shift
    intervention = cell["intervention"]
    for row in intervention.get("closed_corridor_slots", []):
        row["slot"] = int(row["slot"]) + shift
    for row in intervention.get("mission_window_overrides", []):
        if row.get("release_slot") is not None:
            row["release_slot"] = int(row["release_slot"]) + shift
        if row.get("due_slot") is not None:
            row["due_slot"] = int(row["due_slot"]) + shift


def build_calibrated_cell(
    bridge: Any,
    modules: dict[str, Any],
    attempt: dict[str, Any],
    physical_variant: int,
    identity_variant: int,
    base_builder: Any,
) -> dict[str, Any]:
    profile_index = int(attempt["nuisance_profile"])
    cell = base_builder(
        modules,
        attempt["mechanism"], attempt["objective_role"], attempt["target_uav_type"],
        physical_variant, attempt["coupling_topology"],
    )
    _apply_label_independent_time_translation(bridge, cell, profile_index)
    _rehash_cell(bridge, modules, cell, attempt, identity_variant)
    return cell


def construct_candidate(
    bridge: Any,
    modules: dict[str, Any],
    attempt: dict[str, Any],
    candidate_variant: int,
    time_limit: float,
) -> dict[str, Any]:
    original_build = bridge.build_coupled_cell
    candidate_offset = candidate_variant - int(attempt["variant_start"])
    physical_variant = (int(attempt["nuisance_profile"]) + 1) * 4 + candidate_offset

    def overlay(_modules: dict[str, Any], _mechanism: str, _role: str, _target: str, _variant: int, _topology: str):
        if (_mechanism, _role, _target, _variant, _topology) != (
            attempt["mechanism"], attempt["objective_role"], attempt["target_uav_type"],
            physical_variant, attempt["coupling_topology"],
        ):
            raise RuntimeError("CALIBRATION_COORDINATE_DRIFT")
        return build_calibrated_cell(bridge, modules, attempt, physical_variant, candidate_variant, original_build)

    bridge.build_coupled_cell = overlay
    try:
        result = bridge.construct_certificate(
            modules,
            attempt["mechanism"], attempt["objective_role"], attempt["target_uav_type"],
            physical_variant, attempt["coupling_topology"], time_limit,
        )
    finally:
        bridge.build_coupled_cell = original_build
    lineage = {
        "attempt_id": attempt["attempt_id"],
        "attempt_rank": attempt["rank"],
        "ancestor_id": attempt["ancestor_id"],
        "nuisance_profile": attempt["nuisance_profile"],
        "template_family": attempt["template_family"],
        "candidate_variant": candidate_variant,
        "candidate_offset": candidate_offset,
        "physical_variant": physical_variant,
    }
    result["private"]["calibration_lineage"] = lineage
    result["private"]["version"] = VERSION + "_private_certificate"
    result["private"]["certificate_sha256"] = sha_obj({k: v for k, v in result["private"].items() if k != "certificate_sha256"})
    result["public"]["version"] = VERSION + "_public_projection"
    result["public"]["public_projection_sha256"] = sha_obj({k: v for k, v in result["public"].items() if k != "public_projection_sha256"})
    result["summary"].update(lineage)
    result["summary"]["cell_id"] = result["private"]["cell"]["cell_id"]
    result["summary"]["variant"] = candidate_variant
    result["summary"]["certificate_sha256"] = result["private"]["certificate_sha256"]
    result["summary"]["public_projection_sha256"] = result["public"]["public_projection_sha256"]
    return result


def classify_rejection(exc: Exception) -> str:
    message = str(exc)
    known = (
        "MECHANISM_PRESERVING_ALTERNATIVE_NOT_FOUND",
        "SEMANTIC_ROUTE_SOC_INTERVAL_EMPTY",
        "meaningful_positive_gap",
        "MIXED_L5_SOC_INTERVAL_EMPTY",
        "ALTERNATIVE_MECHANISM_NOT_TRUE",
        "TARGET_MECHANISM_NOT_TRUE",
        "DECOUPLED_TARGET_NOT_OPTIMAL",
        "TARGET_NOT_OPTIMAL",
        "ALTERNATIVE_NOT_OPTIMAL",
    )
    for item in known:
        if item in message:
            return item
    return type(exc).__name__ + ":" + message.split(":", 1)[0]


def _write_candidate(output: Path, result: dict[str, Any]) -> None:
    (output / "private").mkdir(parents=True, exist_ok=True)
    (output / "public").mkdir(parents=True, exist_ok=True)
    cid = result["summary"]["cell_id"]
    (output / "private" / f"{cid}.json").write_text(
        json.dumps(result["private"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output / "public" / f"PUB_{cid}.json").write_text(
        json.dumps(result["public"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def verify_manifest(manifest: dict[str, Any], mode: str) -> None:
    attempts = manifest["attempts"]
    expected = len(attempts) if mode == "sentinel" else EXPECTED_ATTEMPTS
    if mode == "sentinel" and (expected < 12 or expected % 12 != 0):
        raise RuntimeError("SENTINEL_DENOMINATOR_INVALID")
    if len(attempts) != expected or [a["rank"] for a in attempts] != list(range(1, expected + 1)):
        raise RuntimeError("MANIFEST_RANK_OR_COUNT_INVALID")
    if len({a["attempt_id"] for a in attempts}) != expected or len({a["ancestor_id"] for a in attempts}) != expected:
        raise RuntimeError("MANIFEST_IDENTITY_DUPLICATE")
    if any(a["opportunity_budget"] != manifest["opportunity_budget_per_attempt"] for a in attempts):
        raise RuntimeError("OPPORTUNITY_BUDGET_DRIFT")
    if mode == "run":
        cells = Counter((a["mechanism"], a["objective_role"]) for a in attempts)
        if set(cells.values()) != {8} or len(cells) != 12:
            raise RuntimeError("CELL_DENOMINATOR_NOT_8")
        if sorted(Counter(a["target_uav_type"] for a in attempts).values()) != [48, 48]:
            raise RuntimeError("TARGET_UAV_BALANCE_INVALID")
        if any(a.get("status") != "REGISTERED_PREOUTCOME" for a in attempts):
            raise RuntimeError("MANIFEST_CONTAINS_OUTCOME")
    declared = manifest.get("manifest_sha256")
    material = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if declared != sha_obj(material):
        raise RuntimeError("MANIFEST_DIGEST_MISMATCH")


def run_manifest(repo: Path, manifest_path: Path, output: Path, mode: str, time_limit: float) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_manifest(manifest, mode)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("OUTPUT_NOT_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    bridge = load_bridge(repo, "candidate_a_calibration_production")
    modules = bridge.load_modules(repo)
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    for attempt in manifest["attempts"]:
        row = {
            **attempt,
            "attempt_status": "REJECTED_NO_ADMITTED_CANDIDATE",
            "candidate_attempt_count": 0,
            "candidate_rejections": [],
            "admitted_cell_id": None,
            "admitted_candidate_variant": None,
        }
        for offset in range(int(attempt["opportunity_budget"])):
            variant = int(attempt["variant_start"]) + offset
            row["candidate_attempt_count"] += 1
            try:
                result = construct_candidate(bridge, modules, attempt, variant, time_limit)
                candidate = {
                    "attempt_id": attempt["attempt_id"], "candidate_offset": offset,
                    "candidate_variant": variant, **result["summary"],
                }
                candidate_rows.append(candidate)
                if result["summary"]["admitted"]:
                    _write_candidate(output, result)
                    row["attempt_status"] = "ADMITTED"
                    row["admitted_cell_id"] = result["summary"]["cell_id"]
                    row["admitted_candidate_variant"] = variant
                    row["admitted_summary"] = result["summary"]
                    break
                reason = "PREDICATE_FALSE"
                rejection_counts[reason] += 1
                row["candidate_rejections"].append({"candidate_variant": variant, "reason": reason})
            except RuntimeError as exc:
                reason = classify_rejection(exc)
                rejection_counts[reason] += 1
                row["candidate_rejections"].append({
                    "candidate_variant": variant, "reason": reason,
                    "exception_type": type(exc).__name__, "message": str(exc),
                })
            except Exception:
                # Unexpected implementation/infrastructure states are not scientific
                # rejection outcomes and must stop the run.
                raise
        outcomes.append(row)
        with (output / "ATTEMPT_OUTCOMES.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    admitted = [row for row in outcomes if row["attempt_status"] == "ADMITTED"]
    summary = {
        "version": VERSION + "_execution_summary",
        "evidence_scope": EVIDENCE_SCOPE,
        "mode": mode,
        "manifest_sha256": manifest["manifest_sha256"],
        "registered_attempt_count": len(outcomes),
        "completed_attempt_count": len(outcomes),
        "admitted_attempt_count": len(admitted),
        "rejected_attempt_count": len(outcomes) - len(admitted),
        "candidate_attempt_count": sum(r["candidate_attempt_count"] for r in outcomes),
        "candidate_rejection_counts": dict(sorted(rejection_counts.items())),
        "production_subsolve_count": int(modules["solve_counter"]["subsolves"]),
        "wall_seconds": round(time.perf_counter() - started, 3),
        "cell_admitted_counts": {
            f"{mechanism}|{role}": sum(
                r["attempt_status"] == "ADMITTED" and r["mechanism"] == mechanism and r["objective_role"] == role
                for r in outcomes
            )
            for mechanism in modules["old"].MECHANISMS for role in modules["old"].ROLES
        },
        "target_uav_registered": dict(Counter(r["target_uav_type"] for r in outcomes)),
        "target_uav_admitted": dict(Counter(r["target_uav_type"] for r in admitted)),
        "topology_registered": dict(Counter(r["coupling_topology"] for r in outcomes)),
        "topology_admitted": dict(Counter(r["coupling_topology"] for r in admitted)),
        "candidate_rows": candidate_rows,
        "attempts": outcomes,
        "formal_confirmation_count": 0,
        "formal_pool_count": 0,
        "model_api_network_call_count": 0,
        "secret_or_dotenv_read_count": 0,
    }
    (output / "POPULATION_CALIBRATION_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "attempts": len(outcomes), "admitted": len(admitted),
        "candidates": summary["candidate_attempt_count"], "subsolves": summary["production_subsolve_count"],
        "wall_seconds": summary["wall_seconds"], "cells": sum(v > 0 for v in summary["cell_admitted_counts"].values()),
    }, sort_keys=True))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--mode", choices=("sentinel", "run"), required=True)
    ap.add_argument("--time-limit", type=float, default=20.0)
    args = ap.parse_args()
    run_manifest(Path(args.repo).resolve(), Path(args.manifest).resolve(), Path(args.output).resolve(), args.mode, args.time_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
