"""Re-solve four route restrictions in enum, finish, and public domains."""
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore
from solve_public_preferences import exact_energy


def main():
    _, _, mods = rescore.runtime()
    core = mods["core"]
    original_options = core.candidate_options
    results = []
    for number in (25, 56, 58, 71):
        rid = f"CA12_CORE_{number:03}"
        private = json.loads((PKG / "data/private/evaluator_records" / f"{rid}.json").read_text(encoding="utf-8"))
        inst, intervention, baseline = private["instance"], private["intervention"], private["baseline"]
        H = inst["horizon_slots"]
        longest = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
        extended = dict(inst, horizon_slots=H + longest + inst["turnaround_slots"] + 2 * inst["max_charge_blocks"] + 1)
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        route_mid = private["selected_pair"]["route"]["mission_id"]
        route_base = next(d["path_id"] for d in baseline["decisions"] if d["mission_id"] == route_mid)
        for domain in ("enum", "finish", "public"):
            def options(instance, inter, mission, *args, **kwargs):
                result = original_options(instance, inter, mission, *args, **kwargs)
                if domain != "enum": result = [o for o in result if o["depart_slot"] < H]
                if domain == "finish": result = [o for o in result if o["charge_start_slot"] + o["charge_blocks"] <= H]
                uav = fleet[mission["uav_id"]]
                paths = {p["path_id"]: p for p in mission["path_options"]}
                inc = mission.get("incoming_deadhead")
                dh = exact_energy(inc, 0, uav, corridors) if inc else 0
                for o in result: o["energy_kwh"] = exact_energy(paths[o["path_id"]], mission["payload_kg"], uav, corridors) + dh
                return result
            core.candidate_options = options
            built = core.build_model(inst if domain == "enum" else extended, intervention, baseline)
            core.candidate_options = original_options
            built["ub"][-2 * len(inst["missions"]):] += 1e-6
            n = len(built["var_meta"])
            for restricted in (False, True):
                A, lb, ub = built["A"], built["lb"], built["ub"]
                for hold in built["hold_idx"].values():
                    vector = np.zeros(n); vector[hold] = 1
                    A = vstack([A, csr_matrix(vector.reshape(1, -1))], format="csr")
                    lb = np.append(lb, 0); ub = np.append(ub, 0)
                if restricted:
                    vector = np.zeros(n)
                    for i in built["option_indices"][route_mid]:
                        if built["var_meta"][i]["path_id"] != route_base: vector[i] = 1
                    A = vstack([A, csr_matrix(vector.reshape(1, -1))], format="csr")
                    lb = np.append(lb, 0); ub = np.append(ub, 0)
                solved = milp(np.zeros(n), integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)),
                              constraints=LinearConstraint(A, lb, ub),
                              options={"time_limit": 30.0, "mip_rel_gap": 0.0, "presolve": True})
                results.append({"record_id": rid, "domain": domain, "route_restricted": restricted,
                                "all_served_feasible": bool(solved.success and solved.status == 0),
                                "solver_status": int(solved.status), "options": n - len(inst["missions"])})
    output = HERE / "certificate_relations/domain_feasibility.json"
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__": main()
