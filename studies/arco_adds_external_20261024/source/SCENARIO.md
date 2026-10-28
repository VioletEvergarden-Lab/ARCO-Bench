# ADDS source and scenarios

The ADDS dataset supplies generated parcel demand and saved simulation geometry
for an urban delivery setting in Katowice, Poland. The ARCO-Bench cases are
simulation-derived networks with an operational background. They are not logs
of observed UAV delivery operations.

Source data and attribution are recorded in `ADDS_README.txt`,
`zenodo_record.json`, and `ADDS_REFERENCES.bib`. The dataset is available at
<https://doi.org/10.5281/zenodo.20491777>. `Data.xlsx` preserves the demand
workbook; `model_geometry.json` and `demand_model_geometry.csv` preserve the
geometry and identifier joins. The saved source-byte segment and extraction
script in `../source_recovery/` reproduce the geometry without running FlexSim.

The five benchmark instances select 36 distinct source records from the
single-parcel, 0.5 kg subset, in workbook order within each locker area.
Each instance has a control and two closure conditions, giving 15 tasks.
ARCO-Bench supplies the aircraft model, three fixed vehicle chains per area,
departure grid, due times, closures, and shared-resource capacities. Each
mission includes outbound delivery and an empty return. Hub capacity counts
movements within one-minute windows; it is not a measured number of physical
landing pads. Exact numerical assumptions are in the task JSON files and
`ADDS_public_instructions.md`.
