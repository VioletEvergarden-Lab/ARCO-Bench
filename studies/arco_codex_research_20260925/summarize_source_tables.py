"""Supplementary group and construct-fidelity rows for new local candidates."""
import csv
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
    sources = {"policy_public": load(HERE / "policy_domains/public_both.jsonl"),
               "local_repair": load(HERE / "local_repair/responses.jsonl"),
               "deepseek_complete": load(PKG / "responses/deepseek_complete.jsonl"),
               "luna_complete": load(PKG / "responses/luna_complete.jsonl")}
    choices = json.loads((HERE / "policy_domains/selection.json").read_text(encoding="utf-8"))["tasks"]
    for policy_name in ("public", "local_repair"):
        for model in ("deepseek_complete", "luna_complete"):
            name = f"{policy_name}+{model}"
            policy = "policy_public" if policy_name == "public" else "local_repair"
            sources[name] = {r["record_id"]: sources[policy if r["selected"] == "policy" else model][r["record_id"]]
                             for r in choices if r["policy"] == policy_name and r["model"] == model}
    output = []
    for name, records in sources.items():
        for rid, raw in sorted(records.items()):
            private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
            scored = sc.score_one(rid, raw, private, mods["core"], mods["formal"], bridge, mods)
            output.append({"source": name, "record_id": rid, "mechanism": private["metadata"]["mechanism"],
                           "admissible": bool(scored["formal_feasible"]),
                           "reference_quality": bool(scored["formal_feasible"] and scored["oracle_equivalent"]),
                           "construct_fidelity": bool(scored["required_repair_semantics"])})
    out = HERE / "source_tables"
    out.mkdir(exist_ok=True)
    with (out / "per_task.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, output[0].keys()); writer.writeheader(); writer.writerows(output)
    summary = {}
    for name in sources:
        r = [x for x in output if x["source"] == name]
        summary[name] = {"admissible": sum(x["admissible"] for x in r), "reference_quality": sum(x["reference_quality"] for x in r),
                         "construct_fidelity": sum(x["construct_fidelity"] for x in r),
                         "groups": {group: {"admissible": sum(x["admissible"] for x in r if x["mechanism"] == group),
                                             "reference_quality": sum(x["reference_quality"] for x in r if x["mechanism"] == group)}
                                    for group in sorted({x["mechanism"] for x in r})}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {j: v for j, v in x.items() if j != "groups"} for k, x in summary.items()}, indent=2))


if __name__ == "__main__": main()
