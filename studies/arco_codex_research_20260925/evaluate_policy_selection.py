"""Actual verifier-gated pair selection for archived and public-domain policy."""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore


def load(path):
    return {r["record_id"]: r.get("raw_text", "") for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def main():
    sc, bridge, mods = rescore.runtime()
    selector = rescore.load("archived_selector", PKG / "vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py")
    variants = {"archived": load(PKG / "responses/policy.jsonl"), "public": load(HERE / "policy_domains/public_both.jsonl"),
                "local_repair": load(HERE / "local_repair/responses.jsonl")}
    models = {name: load(PKG / f"responses/{name}.jsonl") for name in ("deepseek_complete", "luna_complete")}
    scored = {}
    for source, data in {**variants, **models}.items():
        scored[source] = {}
        for rid, raw in data.items():
            private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
            scored[source][rid] = sc.score_one(rid, raw, private, mods["core"], mods["formal"], bridge, mods)
    output = {"summary": {}, "tasks": []}
    for policy_name in variants:
        for model_name in models:
            counts = Counter()
            for rid in sorted(variants[policy_name]):
                p, m = scored[policy_name][rid], scored[model_name][rid]
                pq = bool(p["formal_feasible"] and p["oracle_equivalent"])
                mq = bool(m["formal_feasible"] and m["oracle_equivalent"])
                if pq and mq: counts["both_quality"] += 1
                elif pq: counts["policy_only_quality"] += 1
                elif mq: counts["model_only_quality"] += 1
                else: counts["neither_quality"] += 1
                if p["formal_feasible"] and m["formal_feasible"]:
                    comparison = selector.lex_compare(p["objective_vector"], m["objective_vector"])
                    selected = "policy" if comparison <= 0 else "model"
                elif p["formal_feasible"]: selected = "policy"
                elif m["formal_feasible"]: selected = "model"
                else: selected = "none"
                sr = p if selected == "policy" else m if selected == "model" else None
                quality = bool(sr and sr["formal_feasible"] and sr["oracle_equivalent"])
                counts[f"selected_{selected}"] += 1
                counts["selected_admissible"] += int(sr is not None)
                counts["selected_quality"] += int(quality)
                output["tasks"].append({"record_id": rid, "policy": policy_name, "model": model_name,
                    "policy_admissible": bool(p["formal_feasible"]), "model_admissible": bool(m["formal_feasible"]),
                    "policy_quality": pq, "model_quality": mq, "selected": selected, "selected_quality": quality,
                    "policy_objective": p["objective_vector"], "model_objective": m["objective_vector"]})
            output["summary"][f"{policy_name}+{model_name}"] = dict(counts)
    path = HERE / "policy_domains/selection.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))


if __name__ == "__main__": main()
