"""Time public-domain greedy construction from task load through verification."""
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
sys.path.insert(0, str(PKG))
import rescore
from solve_public_preferences import exact_energy


def main():
    _, _, mods = rescore.runtime()
    core, formal = mods["core"], mods["formal"]
    policy = rescore.load("policy_timing", PKG / "vendor/scripts/run_candidate_a_v12p1_resource_aware_greedy_baseline_v1.py")
    selector = rescore.load("selector_timing", PKG / "vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py")
    original_options = core.candidate_options
    original_feasible = policy.feasible_option
    original_priority = policy.local_priority
    expected = {r["record_id"]: json.loads(r["raw_text"])["decisions"] for r in (json.loads(line) for line in (HERE / "policy_domains/public_both.jsonl").read_text(encoding="utf-8").splitlines())}
    rows = []
    for path in sorted((PKG / "data/public/records").glob("CA12_CORE_*.json")):
        start = time.perf_counter()
        task = json.loads(path.read_text(encoding="utf-8"))
        load_sec = time.perf_counter() - start
        inst, intervention, baseline = task["instance"], task["intervention"], task["baseline"]
        H = inst["horizon_slots"]
        longest = max(p["travel_slots"] for m in inst["missions"] for p in m["path_options"])
        extended = dict(inst, horizon_slots=H + longest + inst["turnaround_slots"] + 2 * inst["max_charge_blocks"] + 1)
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        cache = {}
        def options(instance, inter, mission, *args, **kwargs):
            mid = mission["mission_id"]
            if mid not in cache:
                result = [o for o in original_options(extended, inter, mission, *args, **kwargs) if o["depart_slot"] < H]
                routes = {p["path_id"]: p for p in mission["path_options"]}
                uav = fleet[mission["uav_id"]]
                inc = mission.get("incoming_deadhead")
                dh = exact_energy(inc, 0, uav, corridors) if inc else 0
                for o in result:
                    o["energy_kwh_stored"] = o["energy_kwh"]
                    o["energy_kwh"] = exact_energy(routes[o["path_id"]], mission["payload_kg"], uav, corridors) + dh
                cache[mid] = result
            return cache[mid]
        def feasible(instance, mission, option, state, calendars, maps):
            if option["deadhead_start_slot"] < state[mission["uav_id"]]["clock"]: return False
            corridor, pad, charger = policy.option_events(mission, option)
            resources = instance["resources"]
            for kind, additions, default, override in (("corridor", corridor, resources["corridor_capacity_by_slot_default"], maps["corridor_override"]),
                                                       ("pad", pad, resources["pad_capacity_by_slot_default"], maps["pad_override"]),
                                                       ("charger", charger, resources["charger_capacity_by_slot_default"], maps["charger_override"])):
                if not policy.capacity_ok(calendars[kind], additions, default, override): return False
            uav = maps["fleet"][mission["uav_id"]]
            after_flight = state[mission["uav_id"]]["soc"] - option["energy_kwh"]
            return after_flight >= uav["reserve_kwh"] - 1e-6 and after_flight + option["charge_energy_kwh"] <= uav["battery_capacity_kwh"] + 1e-6
        def priority(option, base, mission, slot):
            return original_priority(dict(option, energy_kwh=option["energy_kwh_stored"]), base, mission, slot)
        core.candidate_options, policy.feasible_option, policy.local_priority = options, feasible, priority
        construct_start = time.perf_counter()
        decisions, _ = policy.construct(inst, intervention, baseline, core)
        construct_sec = time.perf_counter() - construct_start
        core.candidate_options, policy.feasible_option, policy.local_priority = original_options, original_feasible, original_priority
        if decisions != expected[task["record_id"]]: raise RuntimeError(task["record_id"])
        verify_start = time.perf_counter()
        raw = json.dumps({"record_id": task["record_id"], "decisions": decisions})
        parsed, errors = selector.parse_public(raw, task)
        verified = selector.public_evaluate(parsed, errors, task, formal)
        verify_sec = time.perf_counter() - verify_start
        if not verified["formal_feasible"]: raise RuntimeError((task["record_id"], verified))
        rows.append({"record_id": task["record_id"], "load_sec": load_sec, "construct_sec": construct_sec,
                     "verify_sec": verify_sec, "total_sec": time.perf_counter() - start})
    (HERE / "policy_domains/end_to_end_timing.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {"mean": statistics.mean(r[k] for r in rows), "median": statistics.median(r[k] for r in rows)}
                      for k in ("load_sec", "construct_sec", "verify_sec", "total_sec")}, indent=2))


if __name__ == "__main__": main()
