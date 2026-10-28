"""Three-decision MILP neighborhood around the public-domain greedy policy."""
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, vstack

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore
from solve_public_preferences import exact_energy, solve_built


def main():
    out = HERE / "local_repair"
    out.mkdir(exist_ok=True)
    sc, bridge, mods = rescore.runtime()
    core = mods["core"]
    original_options = core.candidate_options
    policy = {r["record_id"]: json.loads(r["raw_text"])["decisions"] for r in (json.loads(line) for line in (HERE / "policy_domains/public_both.jsonl").read_text(encoding="utf-8").splitlines())}
    rows = []
    raw_rows = []
    for path in sorted((PKG / "data/public/records").glob("CA12_CORE_*.json")):
        start = time.perf_counter()
        task = json.loads(path.read_text(encoding="utf-8"))
        rid, inst = task["record_id"], task["instance"]
        H = inst["horizon_slots"]
        longest = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
        extended = dict(inst, horizon_slots=H + longest + inst["turnaround_slots"] + 2 * inst["max_charge_blocks"] + 1)
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        def options(instance, intervention, mission, *args, **kwargs):
            result = [o for o in original_options(instance, intervention, mission, *args, **kwargs) if o["depart_slot"] < H]
            uav = fleet[mission["uav_id"]]
            routes = {p["path_id"]: p for p in mission["path_options"]}
            inc = mission.get("incoming_deadhead")
            deadhead = exact_energy(inc, 0, uav, corridors) if inc else 0
            for o in result:
                o["energy_kwh"] = exact_energy(routes[o["path_id"]], mission["payload_kg"], uav, corridors) + deadhead
            return result
        core.candidate_options = options
        built = core.build_model(extended, task["intervention"], task["baseline"])
        built["ub"][-2 * len(inst["missions"]):] += 1e-6
        core.candidate_options = original_options
        matches = {}
        for decision in policy[rid]:
            mid = decision["mission_id"]
            if decision["held"]:
                chosen = [built["hold_idx"][mid]]
            else:
                chosen = [i for i in built["option_indices"][mid] if all(built["var_meta"][i][k] == decision[k] for k in ("path_id", "depart_slot", "charge_blocks"))]
            if len(chosen) != 1: raise RuntimeError((rid, mid, chosen))
            matches[chosen[0]] = 1.0
        n = len(built["var_meta"])
        vec = np.zeros(n)
        for i in matches: vec[i] = 1
        built["A"] = vstack([built["A"], csr_matrix(vec.reshape(1, -1))], format="csr")
        built["lb"] = np.append(built["lb"], len(inst["missions"]) - 3)
        built["ub"] = np.append(built["ub"], np.inf)
        built["base_constraint_count"] += 1
        solution = solve_built(built, "base", task["baseline"])
        changes = sum(a != b for a, b in zip(policy[rid], solution["decisions"]))
        if changes > 3: raise RuntimeError((rid, changes))
        raw = json.dumps({"record_id": rid, "decisions": solution["decisions"]}, separators=(",", ":"))
        private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
        score = sc.score_one(rid, raw, private, core, mods["formal"], bridge, mods)
        rows.append({"record_id": rid, "changes_from_policy": changes, "objective": score["objective_vector"],
                     "admissible": bool(score["formal_feasible"]), "reference_quality": bool(score["formal_feasible"] and score["oracle_equivalent"]),
                     "runtime_sec": time.perf_counter() - start, "variables": solution["variables"],
                     "constraints": solution["constraints"], "decisions": solution["decisions"]})
        raw_rows.append({"record_id": rid, "raw_text": raw})
    (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    (out / "responses.jsonl").write_text("".join(json.dumps(r) + "\n" for r in raw_rows), encoding="utf-8")
    summary = {"records": len(rows), "admissible": sum(r["admissible"] for r in rows), "reference_quality": sum(r["reference_quality"] for r in rows),
               "changed_tasks": sum(r["changes_from_policy"] > 0 for r in rows),
               "total_runtime_sec": sum(r["runtime_sec"] for r in rows)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
