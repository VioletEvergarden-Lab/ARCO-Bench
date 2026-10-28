0. Project Description

The dataset was created as part of the E-Laas project (Energy optimal urban logistics As A Service).
Project implemented as part of the call ERA-NET Cofund Urban Accessibility and Connectivity (ENUAC China Call) organized by JPI Urban Europe and the National Natural Science Foundation of China (NSFC). This project has received funding from the European Union's Horizon 2020 research and innovation programme under grant agreement No 875022.
E-Laas project is carried out in an international consortium. Project coordinator in Europe: Chalmers University of Technology (Sweden), project coordinator in China: Shanghai University (China), consortium members: Tsinghua University (China), Warsaw University of Technology (Poland), cooperation partners: Stockholms stad, Trafikkontoret (Sweden), ParkUnload (Spain), Metropolis GZM (Poland), Shanghai Urban-Rural Construction and Transportation Department (China), Volvo Group Trucks Technology and Operations (Sweden).
- The Chinese part of the project is funded by National Natural Science Foundation of China.
- The Swedish part of the project is funded by Swedish Energy Agency.
- The Polish part of the project is funded by the National Science Centre, Poland (project no. 2022/04/Y/ST8/00134). The value of the co-financing is PLN 878,107.00. Project duration 27/04/2023-26/04/2026 (36 months).

1. Objective

The purpose of this dataset is to enable the replication and interpretation of the simulation research results presented in the article:
Michał Kłodawski, The use of UAVs in Last-Mile Logistics: opportunities, constraints and potential benefits of Autonomous Drone Delivery Systems (ADDS).

The dataset supports the analysis of last-mile parcel delivery systems with the use of unmanned aerial vehicles (UAVs), with particular attention to demand distribution, parcel-locker locations, wind conditions, UAV speed changes, energy consumption and CO2 emissions.

The dataset includes:
- spatial data describing network nodes and links,
- residential building locations,
- parcel-locker locations,
- parcel demand assigned to buildings and parcel lockers,
- model parameters used in the simulation study,
- wind data used to analyse the influence of wind conditions on UAV operations,
- simulation results for UAV speed under no-wind and wind conditions,
- aggregated comparison of energy consumption and CO2 emissions for different delivery modes,
- FlexSim model file exported in XML format,
- exported FlexSim global tables documenting the internal input and result tables used in the model.

2. License

The data is intended to be provided under the Creative Commons Public Domain (CC0) license, unless otherwise stated in the final repository record.

Dataset DOI: 10.5281/zenodo.20491777

3. Contact

- Contact person: Michał Kłodawski
- ORCID: https://orcid.org/0000-0002-4256-2189
- E-mail: michal.klodawski@pw.edu.pl

4. Dataset Contents

4.1 Data.xlsx

The file contains input data used in the simulation model of last-mile parcel delivery with UAVs and alternative delivery modes.

4.1.1 Data sources

The data were prepared for the simulation study described in the publication. The file includes spatial input data, parcel demand data, parcel-locker data, model parameters and demand records used in the simulation model.

4.1.2 Worksheet structure

4.1.2.1 Nodes

Contains the list of network nodes used in the simulation model.

Data structure:
#Column A: Node_nr - unique network node number,
#Column B: X - X coordinate of the node,
#Column C: y - Y coordinate of the node.

4.1.2.2 Links

Contains the list of directed network links connecting network nodes.

Data structure:
#Column A: Connection_Nr - identifier of the network connection,
#Column B: FROMNODENO - origin node number,
#Column C: TONODENO - destination node number.

4.1.2.3 Residential buildings

Contains the spatial representation of residential buildings used as potential parcel-demand points.

Data structure:
#Column A: ID - residential building identifier,
#Column B: X - X coordinate of the building,
#Column C: Y - Y coordinate of the building,
#Column D: funkcjaOgo - general building function,
#Column E: funkcjaSzc - detailed building function.

4.1.2.4 Parcel lockers

Contains parcel-locker locations and their assignment to the transport network.

Data structure:
#Column A: Node_nr - parcel locker identifier,
#Column B: X - X coordinate of the parcel locker,
#Column C: y - Y coordinate of the parcel locker,
#Column D: Nr - ordinal number of the parcel locker,
#Column E: Node - network node assigned to the parcel locker,
#Column F: dist paczk_node - distance between the parcel locker and the assigned network node.

4.1.2.5 Main parametres

Contains the main parameters used in the simulation model. The worksheet name is preserved as in the original file.

Data structure:
#Column A: Parametr - parameter name,
#Column B: Wartość - parameter value.

The table includes, among others:
- number of parcels,
- average fuel consumption for diesel courier vehicles,
- average fuel consumption for gasoline courier vehicles,
- average energy consumption for electric courier vehicles,
- energy content of diesel and gasoline,
- passenger vehicle structure,
- minimum non-pedestrian travel distance,
- emission conversion factors,
- number of drones assigned to parcel lockers,
- drone flight altitude,
- drone loading and unloading times,
- maximum drone payload,
- maximum drone speed,
- drone speed reduction factor related to payload.

4.1.2.6 Demand

Contains generated parcel demand used in the simulation study.

Data structure:
#Column A: Nr - parcel demand record number,
#Column B: BUD - residential building identifier,
#Column C: PACZ - assigned parcel locker identifier,
#Column D: SZT - number of parcels/items,
#Column E: WAGA - parcel weight [kg],
#Column F: NODE - network node assigned to the delivery building,
#Column G: NODE_PACZ - network node assigned to the parcel locker.

4.2 Results.xlsx

The file contains simulation output data and aggregated comparison of analysed delivery variants.

4.2.1 Data sources

The data were obtained from the simulation model used in the publication.

4.2.2 Worksheet structure

4.2.2.1 Result data

Contains the description of the analysed delivery scenarios.

The research examines four delivery models:
- RS01: courier-to-customer,
- RS02: courier-to-PLs with customers collecting packages,
- RS03: courier-to-PLs, drones assigned to PLs deliver to customers,
- RS04: courier-to-PLs, drones operating in the entire area deliver to customers.

4.2.2.2 RS01

Contains simulation results for scenario RS01: courier-to-customer delivery.

The worksheet includes results by replication and average values for courier delivery directly to the customer's door.

The table includes, among others:
- number of delivered parcels [pcs],
- replication number,
- courier time [s, h],
- courier distance [m, km],
- diesel fuel consumption [l],
- gasoline fuel consumption [l],
- diesel energy consumption [kWh],
- gasoline energy consumption [kWh],
- electric vehicle energy consumption [kWh],
- energy consumption per parcel,
- CO2 emissions and selected per-parcel indicators.

4.2.2.3 RS02

Contains simulation results for scenario RS02: courier-to-parcel-locker delivery with customers collecting packages.

The worksheet includes results for different parcel volumes and assumptions concerning the threshold distance below which recipients collect parcels without using motorized vehicles.

The table includes, among others:
- non-motorized pickup threshold distance [m],
- number of delivered parcels [pcs],
- courier time [h],
- courier distance [km],
- courier fuel and energy consumption,
- recipient travel time and distance,
- energy consumption related to recipient trips,
- CO2 emissions,
- total energy and emission indicators.

4.2.2.4 RS03

Contains simulation results for scenario RS03: courier-to-parcel-locker delivery followed by drone delivery from parcel lockers to customers.

The worksheet includes results for different numbers of drones assigned to each parcel locker.

The table includes, among others:
- number of drones assigned to each parcel locker,
- number of delivered parcels [pcs],
- courier time and distance,
- courier fuel and energy consumption,
- drone operating time,
- drone delivery completion time,
- drone distance,
- drone energy consumption,
- total energy consumption and CO2 emissions.

4.2.2.5 RS04

Contains simulation results for scenario RS04: courier-to-parcel-locker delivery followed by drone delivery, where drones operate in the entire analysed area.

The worksheet includes results for different numbers of drones assigned to the whole area and different parcel volumes.

The table includes, among others:
- number of drones assigned to the area,
- number of delivered parcels [pcs],
- courier time and distance,
- courier fuel and energy consumption,
- drone operating time,
- drone delivery completion time,
- drone distance,
- drone energy consumption,
- total energy consumption and CO2 emissions.

4.3 Tabele w_modelu.xlsx

The file contains exported tables from the FlexSim model. The tables are grouped in the model into two main folders: Data and Results. The exported workbook documents the internal input and result tables used by the simulation model.

Some internal variant-specific result tables are not included as separate worksheets in this workbook because their values are provided in the aggregated result tables in Results.xlsx.

4.3.1 Worksheet structure

4.3.1.1 Tabele

Contains the index of model tables exported from FlexSim.

Data structure:
#Column A: Nazwa - table name,
#Column B: Katalog - folder/group in the FlexSim model, either Data or Results,
#Column C: Krótki opis - short description of the table.

4.3.1.2 Wezly

Contains nodes of the transport network used in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: Node_nr - node identifier,
#Column C: X - X coordinate,
#Column D: y - Y coordinate.

4.3.1.3 Paczkomaty

Contains parcel-locker locations used in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: Node_nr - parcel locker identifier,
#Column C: X - X coordinate,
#Column D: y - Y coordinate,
#Column E: Nr - ordinal number,
#Column F: Node - assigned network node,
#Column G: dist paczk_node - distance between parcel locker and assigned network node.

4.3.1.4 Odcinki

Contains directed links of the transport network used in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: Connection_Nr - connection identifier,
#Column C: FROMNODENO - origin node number,
#Column D: TONODENO - destination node number.

4.3.1.5 Budynki_przeliczone

Contains buildings used as possible delivery destinations in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: ID - building identifier,
#Column C: X - X coordinate,
#Column D: Y - Y coordinate,
#Column E: funkcjaOgo - general building function,
#Column F: funkcjaSzc - detailed building function,
#Column G: Paczkomat - assigned parcel locker,
#Column H: Node - assigned network node,
#Column I: dist bud_node - distance between building and assigned network node,
#Column J: Bud_wielorodzinny - multi-family building flag.

4.3.1.6 Dane

Contains input data and calculation parameters used in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: parameter name,
#Column C: parameter value.

The table contains, among others, parcel volume, courier fuel and energy consumption assumptions, fuel energy values, private vehicle structure, non-motorized pickup threshold distance, emission factors, drone parameters and UAV speed-related assumptions.

4.3.1.7 Dostawy

Contains parcel delivery demand records used in the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: Nr - parcel demand record number,
#Column C: BUD - residential building identifier,
#Column D: PACZ - assigned parcel locker identifier,
#Column E: SZT - number of parcels/items,
#Column F: WAGA - parcel weight [kg],
#Column G: NODE - network node assigned to the delivery building,
#Column H: NODE_PACZ - network node assigned to the parcel locker.

4.3.1.8 Struktura paczek

Contains the parcel weight distribution used to generate parcel demand.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: waga do [kg] - upper weight limit of the parcel class [kg],
#Column C: Share - share of the parcel class [%].

4.3.1.9 Wiatr dane

Contains wind data for Katowice used in the UAV simulation.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: datetime - date and time of wind observation,
#Column C: month - month number,
#Column D: day - day of month,
#Column E: hour - hour of day,
#Column F: minute - minute,
#Column G: wind_dir_8 - wind direction in eight-direction classification,
#Column H: wind_dir_deg - wind direction in degrees,
#Column I: wind_speed_ms - wind speed [m/s],
#Column J: wind_speed_kmh - wind speed [km/h].

4.3.1.10 Wyniki

Contains aggregated simulation results exported from the FlexSim model.

The table includes summary results for analysed variants, including courier, recipient and UAV-related measures.

4.3.1.11 Wyniki_czasy_dronow_w4

Contains detailed UAV movement and energy results for variant 4.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: Dron nr - UAV identifier,
#Column C: t_pion - vertical movement time,
#Column D: t_poz - horizontal movement time,
#Column E: d_pion - vertical movement distance,
#Column F: d_poz - horizontal movement distance,
#Column G: q - parcel weight or payload,
#Column H: V - UAV speed,
#Column I: J/m - energy consumption per meter,
#Column J: J - energy consumption.

4.3.1.12 Predkosci dronow

Contains UAV speed measurements exported from the FlexSim model.

Data structure:
#Column A: row label exported from FlexSim,
#Column B: dron - UAV identifier,
#Column C: vpayload - UAV speed limited by payload,
#Column D: Vground - UAV ground speed,
#Column E: Vwind - wind speed component affecting UAV movement.

4.4 FlexSim_model.fsx

Contains the simulation model in XML format exported from FlexSim.

4.4.1 Model information

- The model should be opened and run in the FlexSim 2025 environment.
- The model represents a last-mile parcel delivery system with the use of unmanned aerial vehicles (UAVs), parcel lockers and courier delivery operations.
- The model contains preconfigured input data, transport network structure, parcel demand data, parcel locker locations, building destination points, UAV parameters, wind-related parameters and result-collection tables.
- The model should be interpreted together with Data.xlsx, Results.xlsx and Tabele w_modelu.xlsx.
- Data.xlsx contains selected input data used in the simulation study.
- Results.xlsx contains aggregated simulation results used for analysis in the publication.
- Tabele w_modelu.xlsx contains exported FlexSim global tables grouped into Data and Results folders.

4.4.2 Main model tables

The model contains, among others, the following global tables in the Data folder:
- Dane - contains input data and parameters used for calculations.
- Wezly - contains nodes of the transport network.
- Odcinki - contains links of the transport network.
- Budynki_przeliczone - contains buildings used as possible destination points.
- Paczkomaty - contains parcel lockers used in the delivery system.
- Dostawy - contains parcel delivery demand records.
- Struktura paczek - contains the parcel weight distribution.
- Wiatr dane - contains wind data used in the UAV simulation.

The model contains, among others, the following global tables in the Results folder:
- Wyniki - contains aggregated simulation results.
- Wyniki_czasy_dronow_w3 - contains detailed UAV movement and energy results for variant 3.
- Wyniki_czasy_dronow_w4 - contains detailed UAV movement and energy results for variant 4.
- Predkosci dronow - contains UAV speed measurements.
- Additional internal variant-specific result tables may be present in the FlexSim model. Their aggregated values are provided in Results.xlsx.

4.4.3 Notes on using the model

- The model is provided as a reference simulation model for the dataset.
- The user should verify the selected model variant and input table values before running a new experiment.
- The result tables may be overwritten when the simulation is run again in FlexSim.
- Due to stochastic simulation logic, repeated runs may produce slightly different detailed outputs unless the same random seeds and settings are used.
- The final aggregated results used for the publication are provided in Results.xlsx.

