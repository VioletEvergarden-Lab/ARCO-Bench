# UAV integrated repair task

Return one complete repair of the disrupted operation described by the public task below. Use the existing mission IDs, assigned UAVs, service order, vehicle types and incoming positioning paths. For each mission choose whether to hold it, a listed service path, an integer service departure, and post-service charging blocks. Holding a mission also holds every later mission on that UAV. Held missions produce no movement, resource occupancy, flight energy or charging. The baseline is the incumbent plan used to measure changes; test the candidate against the intervention-adjusted state.

## Time, paths and interventions

One slot is `instance.slot_min = 5` minutes; turnaround is `instance.turnaround_slots = 1` slot. Replace releases, due slots, initial SOC and resource capacities with the corresponding intervention overrides. Effective release is a hard lower bound on service departure; effective due is a soft arrival target.

For a served mission, choose `0 <= depart_slot < instance.horizon_slots` and `depart_slot >= effective_release_slot`. The horizon bounds service departure. Service, turnaround and charging may finish after the horizon. Apply resource defaults and overrides at every actually occupied slot, including slots after the horizon.

Use each supplied path's `travel_slots` for its scheduled flight duration and `edge_segments` for corridor occupancy. A segment starting at offset `offset_slot` occupies each integer slot from `flight_start + offset_slot` through `flight_start + offset_slot + duration_slots - 1`. Add segment durations to get path duration. These durations are constructed as

`duration_slots = max(1, ceil(base_travel_time_min * UAV.travel_time_coefficient * (1 + 0.06 * segment.wind_level) / 5))`.

Rounding is applied to each segment separately. `travel_time_min_unrounded` is the sum of base segment minutes times the UAV coefficient, before wind adjustment and segment rounding; it is not scheduled elapsed time. A base parameter of 0.05 minutes still contributes at least one scheduled slot. Keep the supplied path data unchanged.

For service departure d and selected service duration t, service arrival is a = d + t; post-service charging starts at g = a + 1 and finishes at f = g + c, where integer c is from 0 through `instance.max_charge_blocks` (3). Even c = 0 leaves the turnaround before the next mission.

If incoming positioning is present, its fixed route starts at b = d - 1 - incoming.travel_slots and arrives at d - 1. Otherwise b = d. The first movement b must be no earlier than the UAV's availability and the previous served mission's f. Fixed per-UAV order follows `sequence_index`. All supplied Core-72 incoming paths are absent; the same rule defines this field when present.

Choose a compatible listed path with the correct endpoints. Its corridors must be authorized, open to flight, spatially continuous and compatible with UAV altitude layers and maximum wind level; mission payload must fit capacity. Exclude every path/start pair whose segment occupancy intersects `closed_corridor_slots`. Listed compatibility does not remove the need to check intervention closures and current capacities.

## Resources and SOC

Count corridor occupancy for all service and incoming segments across all UAVs. Each takeoff and landing consumes one pad movement at that node and event slot; simultaneous movements count separately. Pad capacity counts movements, not every ground-wait slot. Incoming flights contribute their own takeoff and landing events. Charging occupies one destination charger in each slot of [g,f). For each corridor/pad/charger and slot, total usage must not exceed its override capacity when present, otherwise its supplied default. Turnaround and waiting do not separately occupy a charger.

Start from the effective UAV initial SOC. Deduct incoming flight energy (zero payload) and service flight energy (mission payload), then check `SOC >= reserve_kwh`. Next allow destination turnaround and add `c * charge_kwh_per_block`; check the battery capacity. That stored energy is available for later missions. A mission's post-service charge cannot power its own flights or reserve check. Waiting and turnaround consume no additional energy in this model.

Reconstruct flight energy as

`E = sum(corridor.distance_km) * (UAV.empty_energy_kwh_per_km + payload_kg * UAV.payload_energy_kwh_per_km_kg) * (1 + UAV.wind_energy_multiplier_per_level * mean(segment.wind_level))`.

Use the arithmetic mean over segments. The supplied `energy_kwh` is stored to six decimal places; SOC reconstruction uses the formula before rounding. The verifier allows 1e-6 kWh at SOC bounds and 1e-5 kWh when checking stored path energy. A charging block is five minutes and adds the specified stored battery energy. Charging energy is not counted as flight energy.

## Six ordered objectives

Minimize `(L1,L2,L3,L4,L5,L6)` lexicographically: a later tier matters after all earlier tiers match. Do not combine the tiers into a weighted sum. Let h be 1 if held, 0 if served; p,d,c denote the candidate path, departure slot and charge blocks, and p0,d0,c0 the baseline decisions. `[condition]` is 1 when true, otherwise 0.

- L1: number of urgent missions held.
- L2: number of all missions held.
- L3: `1000 * L2` plus, for each mission served in both candidate and baseline, `20*[p!=p0] + abs(d-d0) + 10*[(c>0)!=(c0>0)] + 2*abs(c-c0)`. Departure shift is measured in slots. Missions held in the candidate have no additional contribution; missions held in the baseline have no served baseline-relative contribution.
- L4: sum over served missions of `w * 5 * max(0, arrival_slot - effective_due_slot)`, with w=10 for urgent missions and w=1 otherwise. Unit: priority-weighted minutes.
- L5: sum over served missions of `5 * (max(0, d-effective_release_slot) + c)`. This is release-to-departure plus post-service charging minutes; flight duration is not included.
- L6: total incoming and service flight energy over served missions, in kWh, calculated above.

## Output

Return exactly one JSON object with keys `record_id` and `decisions`. Include every mission exactly once, with exactly these decision fields:

`{"record_id":"<task ID>","decisions":[{"mission_id":"<mission ID>","uav_id":"<assigned UAV ID>","held":false,"path_id":"<listed path ID>","depart_slot":0,"charge_blocks":0}]}`

Use JSON booleans and integer departure/charging fields. For held missions use `held:true`, `path_id:null`, `depart_slot:null`, `charge_blocks:0`. Supply no extra keys, objective claims, Markdown or explanation. You receive one response opportunity with no tools or verifier feedback.
