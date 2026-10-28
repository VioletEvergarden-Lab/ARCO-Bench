"""Independently validate all preference solves with the public verifier."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore


def main():
    _, _, mods = rescore.runtime()
    selector = rescore.load("public_selector_verifier", PKG / "vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py")
    rows = json.loads((HERE / "public_preferences/solves.json").read_text(encoding="utf-8"))["rows"]
    tasks = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (PKG / "data/public/records").glob("CA12_CORE_*.json")}
    references = {r["record_id"]: r["objective"] for r in (json.loads(line) for line in (PKG / "references/public_domain.jsonl").read_text(encoding="utf-8").splitlines())}
    errors = []
    for row in rows:
        rid = row["record_id"]
        task = tasks[rid]
        raw = json.dumps({"record_id": rid, "decisions": row["decisions"]})
        parsed, parse_errors = selector.parse_public(raw, task)
        result = selector.public_evaluate(parsed, parse_errors, task, mods["formal"])
        if not result["formal_feasible"]:
            errors.append({"record_id": rid, "setting": row["setting"], "parse_errors": parse_errors, "formal_errors": result["formal_error_codes"]})
        if row["setting"] == "base":
            ref = references[rid]
            for name in ref:
                if abs(result["objective_vector"][name] - ref[name]) > (1e-4 if name == "energy_kwh" else 0):
                    errors.append({"record_id": rid, "setting": "base", "objective_mismatch": name})
    report = {"solutions": len(rows), "public_verifier_valid": len(rows) - len([x for x in errors if "formal_errors" in x]),
              "base_reference_matches": 72 - len([x for x in errors if x.get("setting") == "base" and "objective_mismatch" in x]), "errors": errors}
    (HERE / "public_preferences/verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, indent=2))
    if errors: raise RuntimeError(f"{len(errors)} verification failures")


if __name__ == "__main__": main()
