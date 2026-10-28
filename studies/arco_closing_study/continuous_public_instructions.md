# UAV logistics plan repair

Return one complete repair for the public task. Preserve mission IDs, assigned UAVs, mission order, endpoints, payloads, listed service paths, and each fixed incoming positioning path. For every mission choose a hold decision or a listed path, service departure and post-service charging count. Holding a mission holds all later missions on that UAV. Held missions produce no movement, flight energy, resource use or charge. Evaluate the repair in the intervention-adjusted state. The baseline is the committed plan used to measure changes.

## Time and physical events

All time fields are minutes; energy is kWh. A service departure d must be a multiple of `timing.departure_grid_min`, satisfy d >= mission.release_min, and be strictly less than `timing.horizon_departure_min`. Due times are soft arrival targets. Only service departure is bounded by the horizon: incoming movement must follow UAV availability and its previous mission, while arrival, turnaround and charging may finish after the horizon. Apply calendars at every used time, including after the departure horizon.

Each listed path includes its actual `flight_min` and `energy_kwh`. They are derived from the supplied directed corridor geometry and M100 phase power model. Use these continuous flight times without rounding to resource windows. With v in m/s, h in m and corridor lengths in km, actual path time is h/v_up/60 + 1000*sum(length)/v_cruise/60 + h/v_down/60. Takeoff time belongs to the first corridor; landing time belongs to the last; middle corridors use cruise time only. Each corridor interval starts after the preceding actual segment durations. All corridors in a path must remain spatially continuous from its origin to destination.

For payload p, induced power is I=((mass_airframe+p)*g)^(3/2)/sqrt(2*rho*A), where A=rotors*pi*(rotor_diameter/2)^2. Phase power is P_r=b1_r*I+b0_r in W. Flight energy is (P_up*t_up + P_cruise*t_cruise + P_down*t_down)/60000 when phase durations are in minutes. Public path coefficients retain full numerical precision. Incoming path coefficients use zero payload. No flying time or energy is added for resource reservation padding. Ground waiting and turnaround consume no energy in this instantiation; ground waiting is allowed only at the aircraft's actual node.

Let t=selected service flight_min, a=d+t, c=integer charge_blocks (0 through 3), q=timing.charge_block_min (5 min), and r=timing.turnaround_min (5 min). Actual service arrival is a, charging starts at g=a+r, and completion is f=g+c*q. Turnaround applies even for c=0. Charging is possible only where the charger calendar provides capacity. A block adds model.charger_input_power_w*model.charging_efficiency*q/60000 kWh to the battery.

If incoming is present, its fixed empty-payload flight starts at b=d-incoming.flight_min-r and lands at d-r. It consumes its own flight energy, corridor intervals and takeoff/landing movements. Otherwise the first movement is b=d. Require b >= UAV.available_min and b >= the previous served mission's f. The UAV starts at initial_vertiport; each incoming origin must match the previous destination, and its destination must match this mission's origin. Without incoming, the previous destination must match this mission's origin.

## Resource calendars

`resources` gives default capacity for each directed corridor, vertiport pad and charger. Every applicable intervention `resource_intervals` entry lowers capacity during its half-open [start_min,end_min) interval. Where intervals overlap, use the minimum of the default and all active limits. `initial_soc_overrides` replaces the corresponding UAV's initial SOC.

For corridor flights and charging, conservatively reserve every resource window [j*w,(j+1)*w) that has a positive-length intersection with the actual interval, where w=timing.resource_window_min. Exact endpoint contact is not an overlap. Every reserved use counts once in that window; if an option has multiple uses of one resource in a window, count each separately. Capacity for a window is the minimum capacity anywhere inside that window, including intervention changes. Sum reservations across all aircraft and require the total <= window capacity. Reservation padding changes capacity accounting only.

Pad capacity is movement throughput per window. Its width is timing.pad_window_min when supplied, otherwise timing.resource_window_min. Count one takeoff at each actual flight start and one landing at each actual flight end. Count every incoming and service movement separately. A movement at t belongs to window floor(t/pad_width), including events after the departure horizon. Pad capacity does not represent ground parking, turnaround occupancy or time spent waiting at a node. Charging occupies a destination charger from g to f when c>0; ground waiting and turnaround do not occupy a charger.

## Battery state

Start with intervention-adjusted initial SOC. Deduct incoming energy before service; deduct service energy before post-service charging. Require the battery to stay at or above reserve_kwh after both flights, before charging. Then add c times the net block charge and require SOC <= battery_capacity_kwh. Later missions may use that stored energy. A post-service charge cannot power the same mission's flight or repair a failed pre-charge reserve check. SOC bound tolerance is 1e-6 kWh.

## Six lexicographic objectives

Minimize these objectives in exactly this order; a later objective cannot compensate for an earlier one:

1. L1: number of held urgent missions.
2. L2: number of held missions of either priority.
3. L3: total committed-plan deviation. A held mission contributes 1000. A served mission contributes 20 if its path_id differs from baseline, plus 0.2*abs(d-baseline.depart_min), plus 10 if charging activation (c>0) differs from baseline, plus 2*abs(c-baseline.charge_blocks).
4. L4: sum over served missions of weight*max(0,a-due_min), with weight 10 for urgent and 1 for routine. Use actual continuous arrivals.
5. L5: sum over served missions of d-release_min+c*q. Count service release waiting and actual charging minutes.
6. L6: total actual incoming plus service flight energy in kWh. Charging energy and ground waiting do not enter L6.

Quality and public candidate comparison use tolerances (0,0,1e-7,1e-5,1e-5,1e-4) for L1 through L6; 1e-4 kWh equals 0.1 Wh. Departure/chain event tolerance is 1e-7 min. These tolerances address numerical comparisons and do not permit changing inputs or relaxing capacity. The optimization contract uses integer L1/L2 and L3 scaled by 5, followed by continuous L4/L5/L6. L1/L2 prefixes are fixed exactly, scaled L3 within 1e-7, and L4/L5 prefixes within 1e-5 min.

## Output

Return exactly one JSON object, with no Markdown or explanatory text:

{"record_id":"the supplied record_id","decisions":[{"mission_id":"M001","uav_id":"U01","held":false,"path_id":"P1","depart_min":12,"charge_blocks":1}]}

Include every mission exactly once. Each decision has exactly the six keys shown. For a held mission use held=true, path_id=null, depart_min=null, charge_blocks=0. For a served mission use a listed path_id, grid-valid numerical depart_min, and an integer charge_blocks in 0..3. Do not output objective estimates or additional keys.
