"""Optimize quality under feasible public-domain construction action restrictions."""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, vstack

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore
from solve_public_preferences import exact_energy, solve_built

TIERS = ("urgent_holds", "total_holds", "repair_distance", "weighted_tardiness_min", "delay_and_charge_wait_min", "energy_kwh")


def add_ban(built, indices):
    if not indices: return
    n = len(built["var_meta"])
    vector = np.zeros(n)
    for i in indices: vector[i] = 1
    built["A"] = vstack([built["A"], csr_matrix(vector.reshape(1, -1))], format="csr")
    built["lb"] = np.append(built["lb"], 0)
    built["ub"] = np.append(built["ub"], 0)
    built["base_constraint_count"] += 1


def main():
    _, _, mods = rescore.runtime()
    core, formal = mods["core"], mods["formal"]
    original_options = core.candidate_options
    source = [json.loads(line) for line in (HERE / "certificate_relations/construction_counterfactuals.source.jsonl").read_text(encoding="utf-8").splitlines()]
    feasible = defaultdict(list)
    for row in source:
        if row["classification"] == "FEASIBLE" and row["kind"] != "full":
            feasible[row["record_id"]].append(row["kind"])
    refs = {r["record_id"]: r["objective"] for r in (json.loads(line) for line in (PKG / "references/public_domain.jsonl").read_text(encoding="utf-8").splitlines())}
    out_rows = []
    for rid, kinds in sorted(feasible.items()):
        private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
        inst, intervention, baseline = private["instance"], private["intervention"], private["baseline"]
        H = inst["horizon_slots"]
        longest = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
        extended = dict(inst, horizon_slots=H + longest + inst["turnaround_slots"] + 2 * inst["max_charge_blocks"] + 1)
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        baseline_map = {d["mission_id"]: d for d in baseline["decisions"]}
        target_uav = private["selected_pair"]["soc"]["uav_id"]
        route_mid = (private["selected_pair"].get("route") or {}).get("mission_id")
        def options(instance, inter, mission, *args, **kwargs):
            result = [o for o in original_options(instance, inter, mission, *args, **kwargs) if o["depart_slot"] < H]
            uav = fleet[mission["uav_id"]]
            paths = {p["path_id"]: p for p in mission["path_options"]}
            inc = mission.get("incoming_deadhead")
            dh = exact_energy(inc, 0, uav, corridors) if inc else 0
            for o in result: o["energy_kwh"] = exact_energy(paths[o["path_id"]], mission["payload_kg"], uav, corridors) + dh
            return result
        core.candidate_options = options
        base_built = core.build_model(extended, intervention, baseline)
        core.candidate_options = original_options
        base_built["ub"][-2 * len(inst["missions"]):] += 1e-6
        for kind in kinds:
            built = {k: v.copy() if hasattr(v, "copy") else v for k, v in base_built.items()}
            add_ban(built, list(built["hold_idx"].values()))
            if kind == "route_disabled":
                add_ban(built, [i for i in built["option_indices"][route_mid]
                                if built["var_meta"][i]["path_id"] != baseline_map[route_mid]["path_id"]])
            elif kind == "routes_fixed":
                for mission in inst["missions"]:
                    if mission["uav_id"] == target_uav:
                        mid = mission["mission_id"]
                        add_ban(built, [i for i in built["option_indices"][mid]
                                        if built["var_meta"][i]["path_id"] != baseline_map[mid]["path_id"]])
            elif kind == "departures_fixed":
                for mission in inst["missions"]:
                    if mission["uav_id"] == target_uav:
                        mid = mission["mission_id"]
                        add_ban(built, [i for i in built["option_indices"][mid]
                                        if built["var_meta"][i]["depart_slot"] != baseline_map[mid]["depart_slot"]])
            else: raise RuntimeError(kind)
            result = solve_built(built, "base", baseline)
            plan = core.make_plan(inst, intervention, "action_quality_analysis", result["decisions"])
            checked = formal.validate_plan(inst, intervention, plan, baseline=baseline)
            if not checked["valid"]: raise RuntimeError((rid, kind, checked["errors"]))
            objective = checked["objective"]
            reference = refs[rid]
            quality = all(objective[name] == reference[name] for name in TIERS[:5]) and abs(objective["energy_kwh"] - reference["energy_kwh"]) <= 1e-4
            out_rows.append({"record_id": rid, "restriction": kind, "reference_quality_feasible": quality,
                             "restricted_objective": objective, "reference_objective": reference,
                             "first_difference": next((name for name in TIERS if abs(objective[name] - reference[name]) > (1e-4 if name == "energy_kwh" else 0)), None),
                             "decisions": result["decisions"]})
    output = HERE / "certificate_relations/action_quality.json"
    output.write_text(json.dumps(out_rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {"feasible": sum(r["restriction"] == k for r in out_rows),
                          "quality_possible": sum(r["restriction"] == k and r["reference_quality_feasible"] for r in out_rows)}
                      for k in sorted({r["restriction"] for r in out_rows})}, indent=2))


if __name__ == "__main__": main()
