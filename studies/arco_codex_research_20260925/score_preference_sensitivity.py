"""Score fixed stored candidates against freshly solved preference references."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import event_ledger

TIERS = ("urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh")
SETTINGS = ("base", "punctuality_first", "route_15", "route_25", "charge_on_8", "charge_on_12")


def jrows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def objective(task, decisions, setting):
    c, _, events = event_ledger.ledger(task, decisions)
    route = int(setting.split("_")[1]) if setting.startswith("route_") else 20
    charge = int(setting.split("_")[2]) if setting.startswith("charge_on_") else 10
    return {"urgent_holds": c.get("urgent_holds", 0), "total_holds": c.get("total_holds", 0),
            "repair_distance": 1000 * c.get("total_holds", 0) + route * c.get("route_changes", 0)
                + c.get("departure_shift_slots", 0) + charge * c.get("charge_activation_changes", 0)
                + 2 * c.get("charge_block_change_abs", 0),
            "weighted_tardiness_min": 10 * c.get("urgent_tardiness_min", 0) + c.get("routine_tardiness_min", 0),
            "delay_and_charge_wait_min": c.get("departure_after_release_min", 0) + c.get("charge_duration_min", 0),
            "energy_kwh": c.get("flight_energy_kwh", 0)}


def order(setting):
    if setting != "punctuality_first": return TIERS
    return TIERS[:2] + (TIERS[3], TIERS[2]) + TIERS[4:]


def compare(a, b, setting):
    for name in order(setting):
        x, y = a[name], b[name]
        if name == "energy_kwh" and abs(x-y) <= 1e-4: continue
        if x < y: return -1
        if x > y: return 1
    return 0


def quality(candidate, reference):
    return all(candidate[name] == reference[name] for name in TIERS[:5]) and abs(candidate["energy_kwh"] - reference["energy_kwh"]) <= 1e-4


def main():
    solves = json.loads((HERE / "public_preferences/solves.json").read_text(encoding="utf-8"))["rows"]
    solve_index = {(r["record_id"], r["setting"]): r for r in solves}
    refs = {r["record_id"]: r["decisions"] for r in jrows(PKG / "references/public_domain.jsonl")}
    source_rows = {"original_reference": refs}
    for name, path in (("policy_public", HERE / "policy_domains/public_both.jsonl"),
                       ("deepseek_complete", PKG / "responses/deepseek_complete.jsonl"),
                       ("luna_complete", PKG / "responses/luna_complete.jsonl")):
        source_rows[name] = {}
        for r in jrows(path):
            try: source_rows[name][r["record_id"]] = json.loads(r["raw_text"])["decisions"]
            except (KeyError, json.JSONDecodeError, TypeError): source_rows[name][r["record_id"]] = None
    selection = json.loads((HERE / "policy_domains/selection.json").read_text(encoding="utf-8"))
    admissible = {(r["record_id"], r["model"]): r["model_admissible"] for r in selection["tasks"] if r["policy"] == "public"}
    tasks = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (PKG / "data/public/records").glob("CA12_CORE_*.json")}
    summary = {}
    detail = []
    for setting in SETTINGS:
        count = Counter()
        for rid, task in sorted(tasks.items()):
            solution = solve_index[(rid, setting)]
            reference = objective(task, solution["decisions"], setting)
            for name in TIERS:
                if abs(reference[name] - solution["objectives"][name]) > (1e-5 if name == "energy_kwh" else 1e-6):
                    raise RuntimeError((rid, setting, name, reference[name], solution["objectives"][name]))
            candidate_obj = {}
            candidate_quality = {}
            for source, data in source_rows.items():
                candidate = data.get(rid)
                valid = candidate is not None and (source not in ("deepseek_complete", "luna_complete") or admissible[(rid, source)])
                if valid:
                    candidate_obj[source] = objective(task, candidate, setting)
                    candidate_quality[source] = quality(candidate_obj[source], reference)
                    count[source + "_quality"] += int(candidate_quality[source])
                else:
                    candidate_obj[source], candidate_quality[source] = None, False
            count["any_fixed_candidate_quality"] += int(any(candidate_quality[s] for s in ("policy_public", "deepseek_complete", "luna_complete")))
            selected = {}
            for model in ("deepseek_complete", "luna_complete"):
                source = "policy_public" if candidate_obj[model] is None or compare(candidate_obj["policy_public"], candidate_obj[model], setting) <= 0 else model
                selected[model] = source
                count[model + "_selected_quality"] += int(candidate_quality[source])
                count[model + "_selected_model"] += int(source == model)
            detail.append({"record_id": rid, "setting": setting, "reference": reference,
                           "reference_decisions": solution["decisions"], "candidate_objectives": candidate_obj,
                           "candidate_quality": candidate_quality, "selected": selected})
        summary[setting] = dict(count)
    out = HERE / "public_preferences"
    (out / "scored_candidates.json").write_text(json.dumps({"summary": summary, "tasks": detail}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
