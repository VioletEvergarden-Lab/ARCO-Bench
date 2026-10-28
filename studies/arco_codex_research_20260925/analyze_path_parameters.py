"""Reconstruct service-path timing and energy from the 72 public tasks."""
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
OUT = HERE / "path_parameters"


def write_csv(path, rows):
    if not rows: return
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, rows[0].keys()); w.writeheader(); w.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    path_rows = []
    by_path = {}
    geometries = set()
    typed_geometries = set()
    for path in sorted((PKG / "data/public/records").glob("CA12_CORE_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        rid, inst = task["record_id"], task["instance"]
        corridors = {c["corridor_id"]: c for c in inst["topology"]["corridors"]}
        fleet = {u["uav_id"]: u for u in inst["fleet"]}
        delta = inst["slot_min"]
        for mission in inst["missions"]:
            uav = fleet[mission["uav_id"]]
            for route in mission["path_options"]:
                geometries.add((rid, tuple(route["corridor_ids"])))
                typed_geometries.add((rid, uav["uav_type"], tuple(route["corridor_ids"])))
                segments = []
                for segment in route["edge_segments"]:
                    corridor = corridors[segment["corridor_id"]]
                    distance = corridor["distance_km"]
                    base = corridor["base_travel_time_min"]
                    wind = segment["wind_level"]
                    continuous = base * uav["travel_time_coefficient"] * (1 + 0.06 * wind)
                    scheduled = delta * max(1, math.ceil(continuous / delta))
                    segments.append((distance, base, wind, continuous, scheduled, segment["duration_slots"]))
                distance = sum(s[0] for s in segments)
                continuous = sum(s[3] for s in segments)
                scheduled = sum(s[4] for s in segments)
                mean_wind = statistics.mean(s[2] for s in segments)
                weighted_wind = sum(s[0] * s[2] for s in segments) / distance
                factor = uav["empty_energy_kwh_per_km"] + mission["payload_kg"] * uav["payload_energy_kwh_per_km_kg"]
                mean_energy = distance * factor * (1 + uav["wind_energy_multiplier_per_level"] * mean_wind)
                weighted_energy = distance * factor * (1 + uav["wind_energy_multiplier_per_level"] * weighted_wind)
                row = {"record_id": rid, "mission_id": mission["mission_id"], "path_id": route["path_id"],
                       "uav_type": uav["uav_type"], "segment_count": len(segments), "distance_km": distance,
                       "uav_time_multiplier": uav["travel_time_coefficient"],
                       "base_minutes": sum(s[1] for s in segments), "stored_no_wind_minutes": route["travel_time_min_unrounded"],
                       "wind_continuous_minutes": continuous, "scheduled_minutes": scheduled,
                       "roundup_minutes": scheduled - continuous,
                       "contains_005": any(s[1] == 0.05 for s in segments),
                       "equal_distance_segments": max(s[0] for s in segments) - min(s[0] for s in segments) < 1e-9,
                       "mean_wind": mean_wind, "distance_weighted_wind": weighted_wind,
                       "mean_energy_kwh": mean_energy, "distance_weighted_energy_kwh": weighted_energy,
                       "energy_formula_difference_kwh": weighted_energy - mean_energy,
                       "stored_energy_kwh": route["energy_kwh"],
                       "segment_slot_match": all(s[4] / delta == s[5] for s in segments)}
                path_rows.append(row)
                by_path[(rid, mission["mission_id"], route["path_id"])] = row
    write_csv(OUT / "service_paths.csv", path_rows)
    l5 = list(csv.DictReader((PKG / "evidence/L5_cases.csv").open(encoding="utf-8-sig")))
    pairs = []
    for case in l5:
        for pair in json.loads(case["changed_paths"]):
            rid, mid = case["record_id"], pair["mission_id"]
            prior = by_path[(rid, mid, pair["reference_path"])]
            after = by_path[(rid, mid, pair["candidate_path"])]
            pairs.append({"record_id": rid, "source": case["source"], "mission_id": mid,
                          "reference_path": pair["reference_path"], "candidate_path": pair["candidate_path"],
                          "delta_distance_km": after["distance_km"] - prior["distance_km"],
                          "delta_continuous_min": after["wind_continuous_minutes"] - prior["wind_continuous_minutes"],
                          "delta_scheduled_min": after["scheduled_minutes"] - prior["scheduled_minutes"],
                          "delta_energy_kwh": after["mean_energy_kwh"] - prior["mean_energy_kwh"],
                          "either_contains_005": bool(after["contains_005"] or prior["contains_005"])})
    write_csv(OUT / "historical_L5_route_pairs.csv", pairs)
    case46 = [r for r in path_rows if r["record_id"] == "CA12_CORE_046"]
    write_csv(OUT / "core_046_paths.csv", case46)
    summary = {"service_path_records": len(path_rows), "records_containing_005": sum(r["contains_005"] for r in path_rows),
               "task_local_geometries": len(geometries), "task_local_uav_type_geometries": len(typed_geometries),
               "tasks_containing_005": len({r["record_id"] for r in path_rows if r["contains_005"]}),
               "segment_slot_matches": sum(r["segment_slot_match"] for r in path_rows),
               "no_wind_field_matches": sum(abs(r["stored_no_wind_minutes"] - r["base_minutes"] * r["uav_time_multiplier"]) < 1e-5 for r in path_rows),
               "equal_distance_segment_paths": sum(r["equal_distance_segments"] for r in path_rows),
               "energy_formula_max_abs_difference_kwh": max(abs(r["energy_formula_difference_kwh"]) for r in path_rows),
               "energy_formula_nonzero_paths": sum(abs(r["energy_formula_difference_kwh"]) > 1e-9 for r in path_rows),
               "roundup_minutes_total": sum(r["roundup_minutes"] for r in path_rows),
               "roundup_minutes_median": statistics.median(r["roundup_minutes"] for r in path_rows),
               "historical_l5_changed_path_pairs": len(pairs),
               "historical_l5_pair_005_count": sum(r["either_contains_005"] for r in pairs),
               "historical_l5_pair_shorter_and_less_energy": sum(r["delta_scheduled_min"] < 0 and r["delta_energy_kwh"] < 0 for r in pairs)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
