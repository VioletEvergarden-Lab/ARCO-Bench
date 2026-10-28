# UAV logistics plan repair

Return one complete repair for the public task. Preserve mission IDs, assigned UAVs, mission order, endpoints, payloads, listed service paths, and every fixed `return_path`. For every mission choose a suffix hold or a listed service path and service departure. All missions in this group have `charge_blocks=0`. Holding a mission holds all later missions on that UAV. Held missions produce no loading, movement, flight energy or resource use. Evaluate the repair in the intervention-adjusted state. The baseline is the committed plan used to measure changes. No optimized reference plan is provided.

## Time, loading, service and fixed return

All time fields are minutes; energy is kWh. A service departure d must be a multiple of `timing.departure_grid_min`, satisfy d >= mission.release_min, and be strictly less than `timing.horizon_departure_min`. The release time bounds the **service departure**. Loading begins at d - timing.load_min, and cannot begin before UAV.available_min or the previous served mission's complete return. Thus, a zero release does not permit a departure whose preceding loading starts before UAV availability. Due times are soft targets for the outbound **delivery arrival**, before unloading and return.

Each served mission is one delivery sortie: load at its origin, fly the selected service path carrying the recorded payload, unload at its destination for timing.unload_min, and immediately fly its fixed `return_path` empty back to the origin hub. Let t_out and t_return be the actual outbound and return flight times. The delivery arrival is a=d+t_out; return departure is a+timing.unload_min; the sortie finishes at a+timing.unload_min+t_return. The next mission's loading must start at or after this finish. UAV positions follow these actual movements. There is no additional turnaround and no incoming positioning path in these tasks. Waiting before loading is ground waiting at the hub. There is no discretionary wait inserted at the delivery building before the fixed return.

Only service departure is bounded by the departure horizon. Loading, outbound arrival, unloading and return use their actual times; apply resource calendars to every movement and flight interval, including return events after the departure horizon. The final executed mission returns to the hub too, including when later missions in that chain are held.

## Flight coefficients and energy

The task uses the supplied directed corridor geometry and physical model. Public path coefficients give actual `flight_min` and `energy_kwh` where supplied. Use continuous flight times without rounding them to decision or resource windows. With v in m/s, h in m and corridor lengths in km, actual path time is h/v_up/60 + 1000*sum(length)/v_cruise/60 + h/v_down/60. Takeoff time belongs to the first corridor; landing time belongs to the last; middle corridors use cruise time only. Each corridor interval starts after preceding actual segment durations. Each path is spatially continuous from its origin to destination.

For payload p, induced power is I=((mass_airframe+p)*g)^(3/2)/sqrt(2*rho*A), where A=rotors*pi*(rotor_diameter/2)^2. Phase power is P_r=b1_r*I+b0_r in W. Flight energy is (P_up*t_up + P_cruise*t_cruise + P_down*t_down)/60000 when phase durations are in minutes. Outbound flight uses mission.payload_kg; fixed return uses zero payload. Ground waiting, loading and unloading consume no flight energy in this instantiation. Reservation padding adds neither flight time nor energy.

Start with intervention-adjusted initial SOC. Deduct outbound flight energy, then empty-return energy. Battery SOC must remain at or above fleet.reserve_kwh after each flight. No mission adds charge, and no replenishment is performed between sorties. The SOC bound tolerance is 1e-6 kWh. The last actual return is included in both the battery checks and total flight energy.

## Shared-resource calendars

`resources` gives default capacity for each directed corridor, node movement pad and charger. Every applicable intervention `resource_intervals` entry lowers capacity during its half-open [start_min,end_min) interval. Where entries overlap, use the minimum of the default and all active limits. `initial_soc_overrides` replaces the corresponding UAV's initial SOC.

For each outbound or return corridor flight, conservatively reserve every resource window [j*w,(j+1)*w) having a positive-length intersection with its actual interval, where w=timing.resource_window_min. Exact endpoint contact is not overlap. Every reserved use counts once in that window; multiple uses by one sortie count separately. Window capacity is the minimum applicable capacity anywhere in that window, including intervention changes. Sum reservations across UAVs and require the total <= window capacity. Actual continuous occupancies also obey applicable capacity.

Pad capacity is movement throughput per window. Its width is timing.pad_window_min when supplied, otherwise timing.resource_window_min. Count one takeoff and one landing for every actual flight, including the fixed return. A movement at t belongs to floor(t/pad_width). For a complete sortie, this means an outbound takeoff at the hub, an outbound landing at the building, a return takeoff at the building, and a return landing at the hub. Count all uses separately even if they fall in the same window. A finer service-departure grid does not shorten a resource window or increase its movement capacity. Pad capacity represents movement throughput, not parking, loading or unloading occupancy. No charging takes place in this group.

## Six lexicographic objectives

Minimize these objectives in this order; a later objective cannot compensate for an earlier one:

1. L1: number of held urgent missions.
2. L2: number of held missions of either priority.
3. L3: total committed-plan deviation. A held mission contributes 1000. A served mission contributes 20 if its path_id differs from baseline, plus 0.2*abs(d-baseline.depart_min), plus 10 if charging activation differs from baseline, plus 2*abs(charge_blocks-baseline.charge_blocks). Charging terms are zero in this group.
4. L4: sum over served missions of weight*max(0,a-due_min), where a is the actual outbound delivery arrival, and weight is 10 for urgent and 1 for routine.
5. L5: sum over served missions of d-release_min+charge_blocks*timing.charge_block_min. It counts waiting to service departure and charging minutes. Loading, unloading and return duration are feasibility components, not additional L5 summands.
6. L6: total actual outbound plus empty-return flight energy in kWh for every served mission, including the final executed sortie of every UAV.

Quality and candidate comparison use tolerances (0,0,1e-7,1e-5,1e-5,1e-4) for L1 through L6; 1e-4 kWh equals 0.1 Wh. Departure/chain event tolerance is 1e-7 min. These numerical tolerances do not permit changing input values or relaxing resource capacity. Fractional departures on the specified grid retain their exact L3 contribution; do not round it to the historical whole-minute grid.

## Output

Return exactly one JSON object, with no Markdown or explanatory text:

{"record_id":"the supplied record_id","decisions":[{"mission_id":"M001","uav_id":"U01","held":false,"path_id":"DIRECT","depart_min":0.5,"charge_blocks":0}]}

Include every mission exactly once. Each decision has exactly the six keys shown. For a held mission use held=true, path_id=null, depart_min=null, charge_blocks=0. For a served mission use a listed path_id, a grid-valid numerical depart_min, and charge_blocks=0. Do not output objective estimates or additional keys. Return paths and their departure times follow the fixed sortie rule and are not separate decisions.
