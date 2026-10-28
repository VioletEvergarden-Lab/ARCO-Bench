"""One full public-domain reference pass with load, build, solve, verification timing."""
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore
from solve_public_preferences import exact_energy, solve_built


def main():
    out = HERE / "public_preferences"
    _, _, mods = rescore.runtime()
    core, formal = mods["core"], mods["formal"]
    selector = rescore.load("reference_timing_verifier", PKG / "vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py")
    original_options = core.candidate_options
    rows = []
    for path in sorted((PKG / "data/public/records").glob("CA12_CORE_*.json")):
        total_start = time.perf_counter()
        load_start = time.perf_counter()
        task = json.loads(path.read_text(encoding="utf-8"))
        load_sec = time.perf_counter() - load_start
        rid, inst = task["record_id"], task["instance"]
        H = inst["horizon_slots"]
        longest = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
        extended = dict(inst, horizon_slots=H + longest + inst["turnaround_slots"] + 2 * inst["max_charge_blocks"] + 1)
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        option_sec = 0.0
        option_count = 0
        def options(instance, intervention, mission, *args, **kwargs):
            nonlocal option_sec, option_count
            start = time.perf_counter()
            result = [o for o in original_options(instance, intervention, mission, *args, **kwargs) if o["depart_slot"] < H]
            uav = fleet[mission["uav_id"]]
            routes = {p["path_id"]: p for p in mission["path_options"]}
            inc = mission.get("incoming_deadhead")
            deadhead = exact_energy(inc, 0, uav, corridors) if inc else 0
            for o in result:
                o["energy_kwh"] = exact_energy(routes[o["path_id"]], mission["payload_kg"], uav, corridors) + deadhead
            option_count += len(result)
            option_sec += time.perf_counter() - start
            return result
        core.candidate_options = options
        build_start = time.perf_counter()
        built = core.build_model(extended, task["intervention"], task["baseline"])
        built["ub"][-2 * len(inst["missions"]):] += 1e-6
        build_sec = time.perf_counter() - build_start
        core.candidate_options = original_options
        solution = solve_built(built, "base", task["baseline"])
        verify_start = time.perf_counter()
        raw = json.dumps({"record_id": rid, "decisions": solution["decisions"]})
        parsed, errors = selector.parse_public(raw, task)
        verified = selector.public_evaluate(parsed, errors, task, formal)
        verify_sec = time.perf_counter() - verify_start
        if not verified["formal_feasible"]:
            raise RuntimeError((rid, errors, verified["formal_error_codes"]))
        rows.append({"record_id": rid, "load_sec": load_sec, "options_sec": option_sec,
                     "model_assembly_sec": build_sec - option_sec, "build_sec": build_sec,
                     "phase_sec": solution["phase_seconds"], "verify_sec": verify_sec,
                     "total_sec": time.perf_counter() - total_start,
                     "options": option_count, "variables": solution["variables"], "constraints": solution["constraints"]})
    (out / "end_to_end_timing.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {"mean": statistics.mean(r[key] for r in rows), "median": statistics.median(r[key] for r in rows)}
                      for key in ("load_sec", "options_sec", "model_assembly_sec", "build_sec", "verify_sec", "total_sec", "options", "variables", "constraints")}, indent=2))


if __name__ == "__main__": main()
