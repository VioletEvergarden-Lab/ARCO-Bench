# Manuscript table source

**Table 1. Operating commitments, controls and constraint interpretation.**
| Component | Mathematical object | Operating meaning |
|---|---|---|
| Fixed assignment and sequence | \(M_u\), vehicle type | Preserve the dispatched vehicle chain |
| Fixed incoming route | Incoming path, if present | Preserve the positioning commitment; its timing follows service departure |
| Service retention | \(h_m\in\{0,1\}\), suffix holds | Continue missions or hold the remaining chain |
| Joint recovery controls | \(p_m,d_m,c_m\) | Reroute, retime and charge after service |
| Shared resources | Corridor-slot, pad-slot and charger-slot capacities | Respect airspace access and facility calendars |
| Energy constraints | Initial SOC, flight use, reserve and capacity | Keep the served chain energy-feasible |

**Table 2. Recovery priorities, units and conditional role.**
| Tier | Measure and unit | Meaning after fixing earlier tiers |
|---|---|---|
| L1 | Urgent missions held; count | Preserve priority service |
| L2 | All missions held; count | Preserve remaining service continuity |
| L3 | Baseline-relative plan-change score; points | Prefer fewer route and charging changes and smaller departure shifts |
| L4 | Priority-weighted tardiness; weighted minutes | Improve punctuality at the same plan-change score |
| L5 | Departure-after-release plus post-service charging; minutes | Prefer earlier service departures and less charging at equal L1–L4 |
| L6 | Incoming plus service flight energy; kWh | Break remaining ties by flight energy |

**Table 3. Candidate outcomes on Core-72, with denominator 72 throughout.**
| Role and source | Schema | Admissible | Reference quality | Construct fidelity |
|---|---:|---:|---:|---:|
| Intervention check: no repair | 72 | 0 | 0 | 0 |
| Rule-based reference: policy | 72 | 72 | 38 | 70 |
| Original panel: V4-Pro (11 Aug) | 72 | 66 | 28 | 63 |
| Original panel: Qwen 3.7-Plus | 64 | 59 | 34 | 58 |
| Original panel: GPT-5.6 Luna | 71 | 70 | 48 | 70 |
| Optimization reference: MILP | 72 | 72 | 72 | 72 |

**Table 4. Action decomposition of recurrent reference gaps. Counts are source-specific occurrences.**
| Observed pattern | V4-Pro | Qwen | Luna | Policy | Operational decomposition relative to reference |
|---|---:|---:|---:|---:|---|
| L3 +1: net one departure-shift slot | 9 | 9 | 3 | 11 | Same aggregate path-change/charging counts; one extra absolute-shift slot |
| L3 +1: charging exchanged for retiming | 5 | 8 | 9 | 7 | +13 absolute-shift slots; −1 charging activation; −1 charge block |
| L5 +55 at equal L1–L4 | 4 | 5 | 6 | 0 | +60 departure-wait minutes; −5 charging minutes; unchanged fleet completion |

**Table 5. Pairwise selection and reference-quality complementarity.**
| Pair | Both quality | Policy only | Model only | Neither | Selected quality | Construct fidelity | Policy/model chosen |
|---|---:|---:|---:|---:|---:|---:|---:|
| Policy + V4-Pro (11 Aug) | 14 | 24 | 14 | 20 | 52 | 72 | 53 / 19 |
| Policy + Qwen | 22 | 16 | 12 | 22 | 50 | 70 | 53 / 19 |
| Policy + Luna | 23 | 15 | 25 | 9 | 63 | 72 | 41 / 31 |

**Table S1. Measured time components; scopes differ across rows.**
| Component | Mean | Median | Additional information | Measurement scope |
|---|---:|---:|---|---|
| MILP six-stage solve | 0.081960 s | 0.074477 s | p95 0.153474 s; max 0.174981 s | After build, before alternative probe |
| Policy generation | 0.091 s | 0.081 s | Stored local generation trace | Enumeration and candidate construction |
| V4-Pro (11 Aug) | 207.41 s | 199.37 s | Hosted service | POST intent to terminal storage |
| Qwen | 230.12 s | 216.19 s | Hosted service | POST intent to terminal storage |
| Luna | 427.03 s | 312.42 s | Hosted service | POST intent to terminal storage |
| Policy + V4-Pro selector | 0.808 ms | 0.817 ms | max 1.298 ms | Both parsers, verifiers and comparison |
| Policy + Qwen selector | 0.757 ms | 0.789 ms | max 1.379 ms | Same local scope |
| Policy + Luna selector | 0.759 ms | 0.765 ms | max 1.053 ms | Same local scope |

**Table B1. UAV_02 reference ledger for CA12_CORE_012.**
| Event | Slot or interval | SOC (kWh) | Operation |
|---|---|---:|---|
| Initial state after intervention | 7 | 2.722988 | Reserve 2.5; no incoming deadhead |
| MISSION_04 service departure | 7 | 2.722988 | PATH_05 |
| MISSION_04 service arrival | 10 | 2.553167 | Subtract 0.169821; reserve margin 0.053167 |
| Destination turnaround | [10,11) | 2.553167 | No charge yet |
| VP_04 charge block | [11,12) | 3.503167 at end | Add 0.95 kWh over five minutes |
| MISSION_01 service departure | 12 | 3.503167 | PATH_08; no incoming deadhead |
| MISSION_01 service arrival | 13 | 3.377535 | Subtract 0.125632; margin 0.877535 |

**Table D1. Exact identities and settings for the original panel. All dates are UTC.**
| Recorded alias and provider | Execution interval | Interface | Generation fields |
|---|---|---|---|
| deepseek-v4-pro, DeepSeek | 2026-08-11 08:15:17–12:24:29 | Chat Completions, nonstream | max_tokens 128000; temperature 0; thinking/effort absent |
| qwen3.7-plus, Qwen service | 2026-08-11 12:24:29–17:00:54 | Chat Completions, SSE | max_tokens 128000; temperature 0; thinking/effort absent |
| gpt-5.6-luna, OpenAI | 2026-08-11 17:00:54–2026-08-12 01:33:22 | Responses, background polling | max_output_tokens 128000; reasoning effort max, mode standard, context current_turn; store false; stream false; tools empty; temperature absent |
