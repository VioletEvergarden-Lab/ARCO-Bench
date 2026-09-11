#!/usr/bin/env python3
"""Solver-free integrity, reduction, closure, authorization, and accounting core."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "integrated_repair_candidate_a_v11_confirmation_hardening_core_v2"
GLOBAL_INVALID = "CONFIRMATION_INVALID_INCOMPLETE_NO_SCIENTIFIC_RATE"
NO_ELIGIBLE = "SCIENTIFIC_FAILURE_NO_ELIGIBLE_PAIR"
PARENT_SUCCESS = "PARENT_SCIENTIFIC_SUCCESS"
PARENT_FAILURE = "PARENT_SCIENTIFIC_FAILURE"
EXPECTED_PARENTS = 64
EXPECTED_PAIRS = 128
EXPECTED_SLOTS = 192
ROLE_PROJECTION_FIELDS = (
    "parent_id", "pair_id", "role_id", "role_requirement",
    "raw_solver_status_class", "normalized_classification",
    "solution_present", "metadata_valid", "accepted",
    "rejection_codes", "structural_codes",
)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [json_safe(v) for v in sorted(value, key=lambda item: json.dumps(json_safe(item), sort_keys=True))]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_obj(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(json_safe(value), indent=2, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)


def payload_without_declared_hashes(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(artifact)
    payload.pop("declared_artifact_sha256", None)
    payload.pop("canonical_payload_sha256", None)
    return payload


def validate_raw_artifact(
    artifact: Any,
    *,
    required_fields: tuple[str, ...] | list[str],
    expected_lineage: dict[str, Any],
    verifier_valid: bool,
    certificate_binding_valid: bool,
    artifact_complete: bool = True,
    native_artifact_hash_valid: bool = True,
    raw_artifact_bytes_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate original bytes/fields before any semantic adapter is allowed."""
    codes: list[str] = []
    if not isinstance(artifact, dict):
        return {"status": GLOBAL_INVALID, "record_integrity_valid": False, "integrity_codes": ["RAW_ARTIFACT_NOT_OBJECT"], "semantic_view_allowed": False}
    missing = [field for field in required_fields if field not in artifact]
    if missing:
        codes.append("REQUIRED_FIELDS_MISSING:" + "|".join(sorted(missing)))
    for key, expected in expected_lineage.items():
        if artifact.get(key) != expected:
            codes.append("LINEAGE_MISMATCH:" + key)
    declared = artifact.get("declared_artifact_sha256")
    declared_canonical = artifact.get("canonical_payload_sha256")
    payload_sha = sha256_obj(artifact.get("payload"))
    expected_declared = raw_artifact_bytes_sha256 or payload_sha
    if not isinstance(declared, str) or declared != expected_declared:
        codes.append("DECLARED_ARTIFACT_HASH_MISMATCH")
    if not isinstance(declared_canonical, str) or declared_canonical != payload_sha:
        codes.append("CANONICAL_PAYLOAD_HASH_MISMATCH")
    if not verifier_valid:
        codes.append("FORMAL_VERIFIER_FAILURE")
    if not certificate_binding_valid:
        codes.append("CERTIFICATE_BINDING_FAILURE")
    if not native_artifact_hash_valid:
        codes.append("NATIVE_DECLARED_ARTIFACT_HASH_MISMATCH")
    if not artifact_complete:
        codes.append("ARTIFACT_INCOMPLETE")
    return {
        "status": "RAW_ARTIFACT_INTEGRITY_PASS" if not codes else GLOBAL_INVALID,
        "record_integrity_valid": not codes,
        "integrity_codes": sorted(set(codes)),
        "raw_artifact_bytes_sha256": expected_declared,
        "raw_payload_sha256": payload_sha,
        "semantic_view_allowed": not codes,
    }


def combine_record_integrity(*rows: dict[str, Any]) -> dict[str, Any]:
    codes: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("record_integrity_valid") is not True:
            if isinstance(row, dict):
                codes.extend(f"ARTIFACT_{index}::{code}" for code in row.get("integrity_codes", ["INTEGRITY_NOT_PROVEN"]))
            else:
                codes.append(f"ARTIFACT_{index}::INTEGRITY_RESULT_MISSING")
    return {
        "status": "COMPOSITE_RECORD_INTEGRITY_PASS" if not codes else GLOBAL_INVALID,
        "record_integrity_valid": not codes,
        "integrity_codes": sorted(set(codes)),
        "constituent_artifact_count": len(rows),
    }


def build_semantic_view_after_integrity(artifact: dict[str, Any], integrity: dict[str, Any], projection_fields: tuple[str, ...] | list[str]) -> dict[str, Any]:
    if integrity.get("record_integrity_valid") is not True:
        return {"status": GLOBAL_INVALID, "derived_view_created": False, "integrity_codes": integrity.get("integrity_codes", ["RAW_INTEGRITY_NOT_PROVEN"])}
    projection = {key: copy.deepcopy(artifact.get(key)) for key in projection_fields}
    return {
        "status": "DERIVED_SEMANTIC_VIEW_VALID",
        "derived_view_created": True,
        "raw_artifact_bytes_sha256": integrity["raw_artifact_bytes_sha256"],
        "canonical_raw_payload_sha256": integrity["raw_payload_sha256"],
        "semantic_projection": projection,
        "derived_view_sha256": sha256_obj(projection),
        "raw_hash_overwritten": False,
    }


def overcritical_result(integrity: dict[str, Any], *, holds: int, route_changes: int = 0, charge_changes: int = 0) -> dict[str, Any]:
    valid = integrity.get("record_integrity_valid") is True
    return {
        "status": "OVERCRITICAL_DIAGNOSTIC_RECORDED" if valid else GLOBAL_INVALID,
        "record_integrity_valid": valid,
        "diagnostic_behavior_status": "HOLD_PRESENT" if holds > 0 else "NO_HOLD_OBSERVED",
        "holds": int(holds),
        "route_changes": int(route_changes),
        "charge_changes": int(charge_changes),
        "enters_primary_parent_boolean": False,
        "integrity_codes": integrity.get("integrity_codes", []),
    }


OBJECTIVE_NAMES = ("urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh")


def _objective_map(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        try: return {name: float(value[name]) for name in OBJECTIVE_NAMES}
        except (KeyError, TypeError, ValueError): return None
    if isinstance(value, list):
        try: return {str(row["name"]): float(row["value"]) for row in value}
        except (KeyError, TypeError, ValueError): return None
    return None


def noop_semantic_result(baseline_objective: Any, noop_objective: Any, integrity: dict[str, Any], inactive_intervention: bool) -> dict[str, Any]:
    if integrity.get("record_integrity_valid") is not True:
        return {"status": GLOBAL_INVALID, "semantic_pass": False, "integrity_codes": integrity.get("integrity_codes", [])}
    baseline, noop = _objective_map(baseline_objective), _objective_map(noop_objective)
    if baseline is None or noop is None:
        return {"status": GLOBAL_INVALID, "semantic_pass": False, "integrity_codes": ["NOOP_OBJECTIVE_METADATA_INCOMPLETE"]}
    first_five = all(baseline[name] == noop[name] for name in OBJECTIVE_NAMES[:5])
    energy_gap = abs(baseline[OBJECTIVE_NAMES[5]] - noop[OBJECTIVE_NAMES[5]])
    passed = bool(inactive_intervention and first_five and energy_gap <= 1e-4)
    return {"status": "NOOP_SEMANTIC_PASS" if passed else "NOOP_SCIENTIFIC_FAILURE", "semantic_pass": passed, "first_five_exact": first_five, "energy_absolute_gap": energy_gap, "energy_tolerance": 1e-4, "decision_identity_required": False, "record_integrity_valid": True}


def binding_v4_result(instance: dict[str, Any], baseline: dict[str, Any], repair: dict[str, Any], pair: dict[str, Any], integrity: dict[str, Any]) -> dict[str, Any]:
    if integrity.get("record_integrity_valid") is not True:
        return {"status": GLOBAL_INVALID, "activation_pass": False, "integrity_codes": integrity.get("integrity_codes", [])}
    missions = {row["mission_id"]: row for row in instance.get("missions", [])}; before = {row["mission_id"]: row for row in baseline.get("decisions", [])}; after = {row["mission_id"]: row for row in repair.get("decisions", [])}; soc = pair.get("soc", {}); target = missions.get(soc.get("soc_target_mission_id"), {}); uav = soc.get("uav_id")
    rows = []
    for mission_id, mission in sorted(missions.items()):
        if mission.get("uav_id") != uav or mission.get("sequence_index", 10**9) >= target.get("sequence_index", -1): continue
        b, a = before.get(mission_id), after.get(mission_id)
        if not b or not a or b.get("held") or a.get("held"): continue
        rows.append((int(b.get("charge_blocks", 0)), int(a.get("charge_blocks", 0))))
    delta = sum(a for _, a in rows) - sum(b for b, _ in rows); no_hold = bool(after) and not any(row.get("held") for row in after.values()); route_change = True; same_chain = True
    if pair.get("route"):
        rid = pair["route"].get("mission_id"); route_change = bool(rid in before and rid in after and not after[rid].get("held") and before[rid].get("path_id") != after[rid].get("path_id")); same_chain = missions.get(rid, {}).get("uav_id") == uav == pair["route"].get("uav_id")
    passed = bool(no_hold and delta > 0 and route_change and same_chain)
    return {"status": "BINDING_V4_PASS" if passed else "BINDING_V4_SCIENTIFIC_FAILURE", "activation_pass": passed, "all_served_no_hold": no_hold, "signed_pre_target_charge_block_delta": delta, "route_target_path_changed": route_change, "same_frozen_uav_causal_chain": same_chain, "record_integrity_valid": True}


def _status_class(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "INVALID_OR_MISSING"
    return {0: "OPTIMAL_OR_FEASIBLE", 1: "LIMIT_REACHED", 2: "PROVEN_INFEASIBLE", 3: "UNBOUNDED_OR_MODEL_ERROR", 4: "SOLVER_ERROR"}.get(value, "UNRECOGNIZED_STATUS")


def semantic_projection(parent_id: str, pair_id: str, role_id: str, role: Any, pair: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(role, dict):
        return {"parent_id": parent_id, "pair_id": pair_id, "role_id": role_id, "role_requirement": None, "raw_solver_status_class": "INVALID_OR_MISSING", "normalized_classification": "MISSING_ROLE", "solution_present": False, "metadata_valid": False, "accepted": bool(pair.get("accepted")), "rejection_codes": sorted(set(pair.get("rejection_codes", []))), "structural_codes": sorted(set(pair.get("structural_rejection_codes", [])))}
    metadata_valid = all(key in role for key in ("solver_status", "solver_message", "solver_success", "classification", "role_requirement"))
    solution_present = bool(role.get("solution_present", role.get("solver_success") is True))
    return {
        "parent_id": parent_id,
        "pair_id": pair_id,
        "role_id": role_id,
        "role_requirement": role.get("role_requirement"),
        "raw_solver_status_class": _status_class(role.get("solver_status")),
        "normalized_classification": role.get("classification", "MISSING_CLASSIFICATION"),
        "solution_present": solution_present,
        "metadata_valid": metadata_valid,
        "accepted": bool(pair.get("accepted")),
        "rejection_codes": sorted(set(pair.get("rejection_codes", []))),
        "structural_codes": sorted(set(pair.get("structural_rejection_codes", pair.get("structural_codes", [])))),
    }


def single_pair_integrity_codes(parent_id: str, pair: dict[str, Any], side: str) -> list[str]:
    codes: list[str] = []
    if pair.get("parent_id") != parent_id:
        codes.append(side + "_PARENT_ID_MISMATCH")
    if not isinstance(pair.get("pair_id"), str) or not isinstance(pair.get("accepted"), bool) or not isinstance(pair.get("roles"), dict) or not isinstance(pair.get("rejection_codes"), list) or not isinstance(pair.get("structural_rejection_codes"), list):
        codes.append(side + "_PAIR_METADATA_MISSING_OR_INVALID")
        return codes
    roles = pair["roles"]
    if not roles and not pair["structural_rejection_codes"]:
        codes.append(side + "_CERTIFICATE_ROLE_METADATA_MISSING")
    role_requirements_satisfied = True
    for role_id, role in sorted(roles.items()):
        projection = semantic_projection(parent_id, pair["pair_id"], role_id, role, pair)
        classification = projection["normalized_classification"]
        status_class = projection["raw_solver_status_class"]
        if not projection["metadata_valid"]:
            codes.append(side + "_ROLE_METADATA_MISSING:" + role_id)
        if classification.startswith(("UNKNOWN", "ERROR", "MISSING")) or status_class in {"LIMIT_REACHED", "UNBOUNDED_OR_MODEL_ERROR", "SOLVER_ERROR", "INVALID_OR_MISSING", "UNRECOGNIZED_STATUS"}:
            codes.append(side + "_ROLE_INTEGRITY_FAILURE:" + role_id)
        if (classification == "FEASIBLE" and (status_class != "OPTIMAL_OR_FEASIBLE" or not projection["solution_present"])) or (classification == "PROVEN_INFEASIBLE" and (status_class != "PROVEN_INFEASIBLE" or projection["solution_present"])):
            codes.append(side + "_ROLE_STATUS_CLASSIFICATION_CONTRADICTION:" + role_id)
        if classification != projection["role_requirement"]:
            role_requirements_satisfied = False
    if pair["accepted"] and (pair["rejection_codes"] or pair["structural_rejection_codes"] or not role_requirements_satisfied):
        codes.append(side + "_ACCEPTED_TRUE_EVIDENCE_CONTRADICTION")
    if not pair["accepted"] and roles and not pair["rejection_codes"] and not pair["structural_rejection_codes"] and role_requirements_satisfied:
        codes.append(side + "_ACCEPTED_FALSE_EVIDENCE_CONTRADICTION")
    return sorted(set(codes))


def compare_pair_evidence(parent_id: str, production: dict[str, Any], independent: dict[str, Any]) -> dict[str, Any]:
    codes: list[str] = single_pair_integrity_codes(parent_id, production, "PRODUCTION") + single_pair_integrity_codes(parent_id, independent, "INDEPENDENT")
    if production.get("pair_id") != independent.get("pair_id"):
        codes.append("PAIR_ID_MISMATCH")
    pair_id = str(production.get("pair_id"))
    proles = production.get("roles") if isinstance(production.get("roles"), dict) else {}
    iroles = independent.get("roles") if isinstance(independent.get("roles"), dict) else {}
    if set(proles) != set(iroles):
        codes.append("ROLE_SET_MISMATCH")
    projections = []
    for role_id in sorted(set(proles) | set(iroles)):
        p = semantic_projection(parent_id, pair_id, role_id, proles.get(role_id), production)
        i = semantic_projection(parent_id, str(independent.get("pair_id")), role_id, iroles.get(role_id), independent)
        fields = [field for field in ROLE_PROJECTION_FIELDS if p.get(field) != i.get(field)]
        if fields:
            codes.append("ROLE_SEMANTIC_MISMATCH:" + role_id + ":" + "|".join(fields))
        projections.append({"role_id": role_id, "production": p, "independent": i, "mismatched_fields": fields})
    if production.get("accepted") != independent.get("accepted"):
        codes.append("PAIR_ACCEPTED_MISMATCH")
    if sorted(set(production.get("rejection_codes", []))) != sorted(set(independent.get("rejection_codes", []))):
        codes.append("PAIR_REJECTION_CODES_MISMATCH")
    if sorted(set(production.get("structural_rejection_codes", []))) != sorted(set(independent.get("structural_rejection_codes", []))):
        codes.append("PAIR_STRUCTURAL_CODES_MISMATCH")
    return {"status": "PAIR_EVIDENCE_MATCH" if not codes else GLOBAL_INVALID, "match": not codes, "integrity_codes": sorted(set(codes)), "role_projections": projections}


def reduce_two_pairs(production: list[dict[str, Any]], independent: list[dict[str, Any]]) -> dict[str, Any]:
    if len(production) != 2 or len(independent) != 2:
        return {"status": GLOBAL_INVALID, "integrity_codes": ["PAIR_TRAVERSAL_NOT_EXACTLY_TWO"]}
    pmap = {row.get("selected_pair_rank"): row for row in production}
    imap = {row.get("selected_pair_rank"): row for row in independent}
    if set(pmap) != {1, 2} or set(imap) != {1, 2}:
        return {"status": GLOBAL_INVALID, "integrity_codes": ["PAIR_RANK_SET_NOT_EXACT_1_2"]}
    comparisons, codes, eligible = [], [], []
    for rank in (1, 2):
        parent_id = str(pmap[rank].get("parent_id"))
        comparison = compare_pair_evidence(parent_id, pmap[rank], imap[rank])
        comparisons.append({"rank": rank, **comparison})
        codes.extend("RANK_%d::%s" % (rank, code) for code in comparison["integrity_codes"])
        if comparison["match"] and pmap[rank].get("accepted") is True:
            eligible.append(rank)
    if codes:
        return {"status": GLOBAL_INVALID, "integrity_codes": sorted(set(codes)), "comparisons": comparisons}
    if not eligible:
        return {"status": NO_ELIGIBLE, "parent_success": False, "selected_pair_rank": None, "comparisons": comparisons}
    rank = min(eligible)
    return {"status": "ELIGIBLE_PAIR_SELECTED", "selected_pair_rank": rank, "selected_pair_id": pmap[rank]["pair_id"], "comparisons": comparisons, "integrity_codes": []}


def parent_reduction(pair: dict[str, Any], noop: dict[str, Any] | None, binding: dict[str, Any] | None, overcritical: dict[str, Any] | None) -> dict[str, Any]:
    if pair.get("status") == GLOBAL_INVALID:
        return {"status": GLOBAL_INVALID, "parent_success": None}
    if pair.get("status") == NO_ELIGIBLE:
        return {"status": NO_ELIGIBLE, "parent_success": False, "terminal_slots": 3, "generated_siblings": 0}
    if not all(isinstance(row, dict) for row in (noop, binding, overcritical)):
        return {"status": GLOBAL_INVALID, "parent_success": None, "integrity_codes": ["SIBLING_RESULT_MISSING"]}
    if any(row.get("status") == GLOBAL_INVALID for row in (noop, binding, overcritical)):
        return {"status": GLOBAL_INVALID, "parent_success": None}
    success = bool(noop.get("semantic_pass") and binding.get("activation_pass"))
    return {"status": PARENT_SUCCESS if success else PARENT_FAILURE, "parent_success": success, "overcritical_behavior_enters_primary": False, "overcritical_record_integrity_valid": overcritical.get("record_integrity_valid")}


def slot_ledger(entries: list[dict[str, Any]], *, global_invalid: bool) -> dict[str, Any]:
    counts = {key: 0 for key in ("scientific_terminal_envelope_slot_count", "generated_sibling_artifact_count", "verifier_valid_generated_record_count", "global_stop_unexecuted_slot_count", "attempted_but_integrity_invalid_artifact_count")}
    for row in entries:
        kind = row.get("slot_kind")
        if kind == "SCIENTIFIC_TERMINAL_ENVELOPE":
            counts["scientific_terminal_envelope_slot_count"] += 1
        elif kind == "GENERATED_SIBLING":
            counts["generated_sibling_artifact_count"] += 1
            if row.get("verifier_valid") and row.get("integrity_valid"):
                counts["verifier_valid_generated_record_count"] += 1
            if not row.get("integrity_valid"):
                counts["attempted_but_integrity_invalid_artifact_count"] += 1
        elif kind == "GLOBAL_STOP_UNEXECUTED":
            counts["global_stop_unexecuted_slot_count"] += 1
    accounted = counts["scientific_terminal_envelope_slot_count"] + counts["generated_sibling_artifact_count"] + counts["global_stop_unexecuted_slot_count"]
    valid = len(entries) == EXPECTED_SLOTS and accounted == EXPECTED_SLOTS and (global_invalid or counts["global_stop_unexecuted_slot_count"] == 0)
    return {"preregistered_record_slot_count": EXPECTED_SLOTS, **counts, "slot_identity_holds": valid, "scientific_rate_publishable": not global_invalid and valid, "status": "SLOT_LEDGER_VALID" if valid else GLOBAL_INVALID, "terminal_envelope_is_benchmark_record": False, "terminal_envelope_is_generated_sibling": False, "audit_only_incomplete": bool(global_invalid)}


def normalized_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("BINDING_PATH_NOT_NORMALIZED_POSIX_RELATIVE")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) or ":" in pure.parts[0]:
        raise ValueError("BINDING_PATH_ROOT_ESCAPE_OR_NONCANONICAL")
    return pure.as_posix()


def _has_disallowed_indirection(base: Path, target: Path) -> bool:
    current = base
    try:
        relative = target.relative_to(base)
    except ValueError:
        return True
    isjunction = getattr(os.path, "isjunction", lambda _: False)
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or isjunction(current):
            return True
    return False


def verify_actual_bindings(repo: Path, phase: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors, checked, seen = [], [], {}
    for index, row in enumerate(rows):
        try:
            rel = normalized_relative_path(row.get("path"))
        except Exception as exc:
            errors.append(f"ROW_{index}_PATH_INVALID:{type(exc).__name__}")
            continue
        key = rel.casefold()
        if key in seen:
            errors.append(f"ROW_{index}_DUPLICATE_NORMALIZED_OR_CASE_COLLISION:{rel}")
            continue
        seen[key] = rel
        scope = row.get("scope")
        base = phase if scope == "phase" else repo if scope in {"source", "historical", "repo"} else None
        if base is None:
            errors.append(f"ROW_{index}_INVALID_SCOPE:{scope}")
            continue
        base_resolved = base.resolve()
        candidate = base_resolved / Path(*PurePosixPath(rel).parts)
        if _has_disallowed_indirection(base_resolved, candidate):
            errors.append(f"ROW_{index}_SYMLINK_OR_JUNCTION:{rel}")
            continue
        target = candidate.resolve(strict=False)
        try:
            target.relative_to(base_resolved)
        except ValueError:
            errors.append(f"ROW_{index}_ROOT_ESCAPE:{rel}")
            continue
        if not target.is_file():
            errors.append(f"ROW_{index}_MISSING_FILE:{rel}")
            continue
        actual_sha, actual_size = sha256_file(target), target.stat().st_size
        if actual_sha != row.get("sha256"):
            errors.append(f"ROW_{index}_SHA_MISMATCH:{rel}")
        if "bytes" in row and actual_size != row.get("bytes"):
            errors.append(f"ROW_{index}_SIZE_MISMATCH:{rel}")
        checked.append({"scope": scope, "path": rel, "sha256": actual_sha, "bytes": actual_size})
    verified_root = hashlib.sha256("".join(f"{row['scope']}:{row['path']}:{row['sha256']}\n" for row in sorted(checked, key=lambda x: (x["scope"], x["path"]))).encode()).hexdigest()
    return {"status": "PASS" if not errors and len(checked) == len(rows) else "FAIL", "errors": errors, "checked_count": len(checked), "verified_rows": checked, "verified_covered_root_sha256": verified_root}


def verify_detached_manifest(repo: Path, phase: Path, manifest_path: Path, *, expected_file_sha: str, expected_canonical_sha: str, expected_root_sha: str) -> dict[str, Any]:
    sidecars = {name: Path(str(manifest_path) + "." + name + ".sha256") for name in ("file", "canonical", "covered_root")}
    if not manifest_path.is_file() or not all(path.is_file() for path in sidecars.values()):
        return {"status": "FAIL", "errors": ["MANIFEST_OR_SIDECAR_MISSING"]}
    document = load_json(manifest_path)
    payload = copy.deepcopy(document)
    declared = payload.pop("canonical_payload_sha256", None)
    file_sha, canonical_sha = sha256_file(manifest_path), sha256_obj(payload)
    bindings = document.get("bindings", [])
    closure = verify_actual_bindings(repo, phase, bindings)
    errors = list(closure["errors"])
    observed = {"file": file_sha, "canonical": canonical_sha, "covered_root": closure["verified_covered_root_sha256"]}
    expected = {"file": expected_file_sha, "canonical": expected_canonical_sha, "covered_root": expected_root_sha}
    for key in expected:
        side_value = sidecars[key].read_text(encoding="ascii").strip()
        if observed[key] != expected[key] or observed[key] != side_value:
            errors.append(key.upper() + "_DIGEST_MISMATCH")
    if declared != canonical_sha:
        errors.append("DECLARED_CANONICAL_MISMATCH")
    return {"status": "PASS" if not errors else "FAIL", "errors": sorted(set(errors)), "observed": observed, "closure": closure, "document": document}


def exclusive_create_run_claim(marker: Path, payload: dict[str, Any]) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(marker), flags)
    try:
        os.write(descriptor, canonical_bytes(payload) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
