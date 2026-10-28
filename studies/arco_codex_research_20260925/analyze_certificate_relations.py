"""Reconstruct the four route-restriction domain changes as public events."""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import event_ledger
import rescore


def main():
    out = HERE / "certificate_relations"
    out.mkdir(exist_ok=True)
    restriction_rows = list(csv.DictReader((PKG / "evidence/route_restriction_optima.csv").open(encoding="utf-8-sig")))
    counterfactual_rows = {r["record_id"]: r for r in csv.DictReader((PKG / "evidence/changed_construction_counterfactuals.csv").open(encoding="utf-8-sig"))}
    refs = {r["record_id"]: r for r in (json.loads(line) for line in (PKG / "references/public_domain.jsonl").read_text(encoding="utf-8").splitlines())}
    _, _, mods = rescore.runtime()
    core, formal = mods["core"], mods["formal"]
    result = []
    for row in restriction_rows:
        rid = row["record_id"]
        task = json.loads((PKG / "data/public/records" / f"{rid}.json").read_text(encoding="utf-8"))
        private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
        inverse = {internal: public for public, internal in private["public_to_internal_id"].items()}
        internal_decisions = json.loads(row["decisions"])
        decisions = [{k: inverse.get(v, v) if k in ("mission_id", "uav_id", "path_id") and v is not None else v for k, v in d.items()} for d in internal_decisions]
        components, vector, events = event_ledger.ledger(task, decisions)
        stored_ref = refs[rid]["objective"]
        restricted_obj = json.loads(row["restricted_objective"])
        if any(abs(vector[i] - restricted_obj[name]) > (1e-4 if i == 5 else 0) for i, name in enumerate(("urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh"))):
            raise RuntimeError(f"Restricted objective mismatch: {rid}")
        H = task["instance"]["horizon_slots"]
        late = [e for e in events if not e["held"] and e["completion_slot"] > H]
        result.append({"record_id": rid, "horizon": H, "restricted_L3": vector[2], "reference_L3": stored_ref["repair_distance"],
                       "L3_excess": vector[2] - stored_ref["repair_distance"], "restricted_L4": vector[3],
                       "reference_L4": stored_ref["weighted_tardiness_min"], "late_completion_count": len(late),
                       "late_events": [{k: e[k] for k in ("mission_id", "uav_id", "path_id", "depart_slot", "arrival_slot", "completion_slot", "charge_blocks", "reserve_margin_kwh", "flight_energy_kwh")} for e in late],
                       "completion_max": max(e["completion_slot"] for e in events if not e["held"]),
                       "public_full_service": vector[:2] == [0, 0], "enum_all_service": False,
                       "finish_all_service": False, "restriction": "retain designated incumbent route",
                       "public_decisions": decisions, "all_events": events,
                       "source_record": "evidence/route_restriction_optima.csv",
                       "public_feasible_witness_record": counterfactual_rows[rid]["public_parser_verifier_valid"]})
    (out / "four_route_cases.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{k: r[k] for k in ("record_id", "horizon", "L3_excess", "restricted_L4", "late_events", "completion_max")} for r in result], indent=2))


if __name__ == "__main__": main()
