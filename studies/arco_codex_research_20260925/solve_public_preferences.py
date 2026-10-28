"""Public-domain reference solves and a fixed six-setting objective probe."""
from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore

SETTINGS = ("base", "punctuality_first", "route_15", "route_25", "charge_on_8", "charge_on_12")


def exact_energy(path, payload, uav, corridors):
    distance = sum(corridors[c]["distance_km"] for c in path["corridor_ids"])
    winds = [seg["wind_level"] for seg in path["edge_segments"]]
    return distance * (uav["empty_energy_kwh_per_km"] + payload * uav["payload_energy_kwh_per_km_kg"]) * (1 + uav["wind_energy_multiplier_per_level"] * statistics.mean(winds))


def solve_built(built, setting, baseline):
    names = [name for name, _ in built["tiers"]]
    vectors = {name: c.copy() for name, c in built["tiers"]}
    if setting.startswith("route_") or setting.startswith("charge_on_"):
        route = int(setting.split("_")[1]) if setting.startswith("route_") else 20
        charge = int(setting.split("_")[2]) if setting.startswith("charge_on_") else 10
        by_mid = {d["mission_id"]: d for d in baseline["decisions"]}
        repair = vectors["repair_distance"]
        for i, option in enumerate(built["var_meta"]):
            if option["kind"] == "hold": continue
            prior = by_mid[option["mission_id"]]
            repair[i] += (route - 20) * int(option["path_id"] != prior["path_id"])
            repair[i] += (charge - 10) * int((option["charge_blocks"] > 0) != (prior["charge_blocks"] > 0))
    if setting == "punctuality_first":
        names[2], names[3] = names[3], names[2]
    A, lb, ub = built["A"], built["lb"], built["ub"]
    n = len(built["var_meta"])
    phase_times, values = {}, {}
    last = None
    for name in names:
        c = vectors[name]
        start = time.perf_counter()
        result = milp(c, integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)),
                      constraints=LinearConstraint(A, lb, ub),
                      options={"time_limit": 30.0, "mip_rel_gap": 0.0, "presolve": True})
        phase_times[name] = time.perf_counter() - start
        if not result.success or result.status != 0:
            raise RuntimeError(f"{setting}: {name}: {result.message}")
        value = float(np.dot(c, result.x))
        values[name] = value
        A = vstack([A, csr_matrix(c.reshape(1, -1))], format="csr")
        lb = np.append(lb, -np.inf)
        ub = np.append(ub, value + 1e-7)
        last = result
    decisions = []
    for mission_id, hold in built["hold_idx"].items():
        if last.x[hold] > 0.5:
            option = {"mission_id": mission_id, "uav_id": built["var_meta"][hold]["uav_id"], "held": True, "path_id": None, "depart_slot": None, "charge_blocks": 0}
        else:
            chosen = [i for i in built["option_indices"][mission_id] if last.x[i] > 0.5]
            if len(chosen) != 1: raise RuntimeError(f"Option extraction {mission_id}: {chosen}")
            m = built["var_meta"][chosen[0]]
            option = {"mission_id": mission_id, "uav_id": m["uav_id"], "held": False,
                      "path_id": m["path_id"], "depart_slot": m["depart_slot"], "charge_blocks": m["charge_blocks"]}
        decisions.append(option)
    return {"objectives": values, "decisions": decisions, "phase_seconds": phase_times,
            "mip_gap": float(last.mip_gap or 0), "variables": n, "constraints": built["base_constraint_count"]}


def main():
    out = HERE / "public_preferences"
    out.mkdir(exist_ok=True)
    _, _, mods = rescore.runtime()
    core, formal = mods["core"], mods["formal"]
    original_options = core.candidate_options
    tasks = sorted((PKG / "data/public/records").glob("CA12_CORE_*.json"))
    archived_ref = {r["record_id"]: r for r in (json.loads(line) for line in (PKG / "references/public_domain.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())}
    all_rows = []
    for index, path in enumerate(tasks, 1):
        task = json.loads(path.read_text(encoding="utf-8"))
        rid = task["record_id"]
        instance = task["instance"]
        H = instance["horizon_slots"]
        longest = max(p["travel_slots"] for m in instance["missions"] for p in m["path_options"])
        extended = dict(instance)
        extended["horizon_slots"] = H + longest + instance["turnaround_slots"] + 2 * instance["max_charge_blocks"] + 1
        corridors = {c["corridor_id"]: c for c in instance["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in instance["fleet"]}
        def options(inst, intervention, mission, *args, **kwargs):
            result = [o for o in original_options(inst, intervention, mission, *args, **kwargs) if o["depart_slot"] < H]
            uav = fleet[mission["uav_id"]]
            pmap = {p["path_id"]: p for p in mission["path_options"]}
            incoming = mission.get("incoming_deadhead")
            dh = exact_energy(incoming, 0, uav, corridors) if incoming else 0
            for o in result:
                o["energy_kwh"] = exact_energy(pmap[o["path_id"]], mission["payload_kg"], uav, corridors) + dh
            return result
        core.candidate_options = options
        start = time.perf_counter()
        built = core.build_model(extended, task["intervention"], task["baseline"])
        # Match the public verifier's SOC feasibility allowance on the final
        # reserve/capacity rows of the archived option formulation.
        built["ub"][-2 * len(instance["missions"]):] += 1e-6
        build_sec = time.perf_counter() - start
        core.candidate_options = original_options
        for setting in SETTINGS:
            solution = solve_built(built, setting, task["baseline"])
            solution.update({"record_id": rid, "setting": setting, "build_seconds": build_sec})
            all_rows.append(solution)
        if index % 6 == 0:
            print(index, "/72; last build", round(build_sec, 3), "sec", flush=True)
    output = {"environment": {"platform": platform.platform(), "processor": platform.processor(),
        "python": sys.version, "scipy": scipy.__version__, "numpy": np.__version__,
        "solver": "scipy.optimize.milp / bundled HiGHS", "threads": "solver default"}, "rows": all_rows}
    (out / "solves.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("Saved", len(all_rows), "solutions", flush=True)


if __name__ == "__main__": main()
