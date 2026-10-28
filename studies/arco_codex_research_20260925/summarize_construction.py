"""Summarize construction population, restrictions, and selected structure."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
POP = HERE / "certificate_relations/POPULATION_SUMMARY.source.json"


def main():
    out = HERE / "certificate_relations"
    out.mkdir(exist_ok=True)
    pop = json.loads(POP.read_text(encoding="utf-8"))
    private = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PKG / "data/private/evaluator_records").glob("CA12_CORE_*.json"))]
    restrictions = [json.loads(line) for line in (HERE / "certificate_relations/construction_counterfactuals.source.jsonl").read_text(encoding="utf-8").splitlines()]
    template = defaultdict(list)
    for p in private:
        template[(p["metadata"]["structural_template_sha256"], p["metadata"]["mechanism"])].append(p["record_id"])
    result = {"prospective_population": {k: pop[k] for k in ("registered_attempt_count", "candidate_attempt_count", "admitted_attempt_count", "rejected_attempt_count", "candidate_rejection_counts", "formal_confirmation_count", "model_api_network_call_count")},
              "selected_core72": len(private),
              "templates": [{"template_id": k[0], "mechanism": k[1], "count": len(v), "tasks": v} for k, v in sorted(template.items(), key=lambda x: len(x[1]))],
              "topologies": dict(Counter(p["metadata"]["coupling_topology"] for p in private)),
              "mechanisms": dict(Counter(p["metadata"]["mechanism"] for p in private)),
              "objective_roles": dict(Counter(p["metadata"]["objective_role"] for p in private)),
              "restrictions": {kind: dict(Counter(r["classification"] for r in restrictions if r["kind"] == kind)) for kind in sorted({r["kind"] for r in restrictions})},
              "capacity": {}}
    capacity = list(csv.DictReader((PKG / "evidence/capacity_counterfactuals.csv").open(encoding="utf-8-sig")))
    for key in ("target_decisions_changed", "competitor_decisions_changed", "resource_order_changed", "gap_changed", "capacity_rejects_at_least_one"):
        result["capacity"][key] = sum(r[key] == "True" for r in capacity)
    (out / "construction_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "templates"}, indent=2))


if __name__ == "__main__": main()
