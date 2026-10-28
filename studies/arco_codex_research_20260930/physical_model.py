"""An isolated M100 parameter model; original Core-72 verifier files are intact."""
import copy
import math
from common import Runtime, event_ledger

MODEL={'version':'M100_Rodrigues_arxiv_v1_20211122','airframe_instrumented_mass_kg':3.680,
       'rotor_diameter_m':13*0.0254,'rotors':4,'air_density_kg_m3':1.225,'g_m_s2':9.80665,
       'cruise_speed_m_s':10.0,'cruise_altitude_m':25.0,'takeoff_speed_m_s':2.5,'landing_speed_m_s':2.0,
       'power_coefficients':{'takeoff':[1.97,13.8],'cruise':[1.69,16.8],'landing':[1.62,-4.7]},
       'battery_capacity_kwh':0.0999,'reserve_fraction':0.20,'initial_fraction':0.80,
       'charger_input_power_w':100.,'charging_efficiency':0.88,'slot_min':5,'max_charge_minutes':15}

def power(payload,regime,params=MODEL):
    area=params['rotors']*math.pi*(params['rotor_diameter_m']/2)**2
    induced=((params['airframe_instrumented_mass_kg']+payload)*params['g_m_s2'])**1.5/math.sqrt(2*params['air_density_kg_m3']*area)
    b1,b0=params['power_coefficients'][regime]
    return b1*induced+b0

def durations(path,uav,corridors):
    p=uav['physical_parameters']; ids=path['corridor_ids']
    seconds=[corridors[c]['distance_km']*1000/p['cruise_speed_m_s'] for c in ids]
    seconds[0]+=p['cruise_altitude_m']/p['takeoff_speed_m_s']
    seconds[-1]+=p['cruise_altitude_m']/p['landing_speed_m_s']
    return seconds

def energy(path,payload,uav,corridors):
    p=uav['physical_parameters']; d=sum(corridors[c]['distance_km'] for c in path['corridor_ids'])*1000
    seconds={'takeoff':p['cruise_altitude_m']/p['takeoff_speed_m_s'],'cruise':d/p['cruise_speed_m_s'],'landing':p['cruise_altitude_m']/p['landing_speed_m_s']}
    return sum(power(payload,r,p)*t for r,t in seconds.items())/3_600_000

def verify_path(path,mission,uav,corridors):
    """Independent geometry/time/power reconstruction for the new physical layer."""
    p=uav['physical_parameters']; payload=mission['payload_kg'] if mission else 0.
    current=mission['origin_vertiport'] if mission else path['node_sequence'][0]
    ids=path['corridor_ids']; segs=path['edge_segments']
    if len(ids)!=len(segs): return None,'PATH_SEGMENT_MISMATCH'
    distance=0.; offset=0; occ=[]; flight_seconds=0.
    for index,(cid,seg) in enumerate(zip(ids,segs)):
        if cid not in corridors: return None,'UNKNOWN_CORRIDOR'
        c=corridors[cid]; points=c['geometry_xy_km']
        length=sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:]))
        if abs(length-c['distance_km'])>1e-9: return None,'GEOMETRY_DISTANCE_MISMATCH'
        if c['from_vertiport']!=current: return None,'SPATIAL_DISCONTINUITY'
        if not c.get('authorized',True) or c.get('weather_closed',False) or c.get('no_fly',False): return None,'INCOMPATIBLE_CORRIDOR_STATUS'
        if c['altitude_layer'] not in uav['compatible_layers'] or seg['wind_level']!=0: return None,'INCOMPATIBLE_UAV_PATH'
        seconds=1000*length/p['cruise_speed_m_s']
        if index==0: seconds+=p['cruise_altitude_m']/p['takeoff_speed_m_s']
        if index==len(ids)-1: seconds+=p['cruise_altitude_m']/p['landing_speed_m_s']
        duration=max(1,math.ceil(seconds/(60*MODEL['slot_min'])))
        if seg['corridor_id']!=cid or seg['offset_slot']!=offset or seg['duration_slots']!=duration: return None,'TRAVEL_TIME_COEFFICIENT_MISMATCH'
        occ.extend((cid,offset+k) for k in range(duration)); offset+=duration; distance+=length; flight_seconds+=seconds; current=c['to_vertiport']
    dest=mission['destination_vertiport'] if mission else path['node_sequence'][-1]
    if current!=dest or path['travel_slots']!=offset: return None,'PATH_ENDPOINT_MISMATCH'
    if payload>0.5+1e-9: return None,'PAYLOAD_CAPACITY_VIOLATION'
    if abs(path['travel_time_min_unrounded']*60-flight_seconds)>1e-7: return None,'CONTINUOUS_TIME_MISMATCH'
    # Kept independent of the generator's power()/energy() implementation.
    disk=p['rotors']*math.pi*p['rotor_diameter_m']**2/4
    pi=((p['airframe_instrumented_mass_kg']+payload)*p['g_m_s2'])**1.5/(2*p['air_density_kg_m3']*disk)**.5
    tc=distance*1000/p['cruise_speed_m_s']; tu=p['cruise_altitude_m']/p['takeoff_speed_m_s']; td=p['cruise_altitude_m']/p['landing_speed_m_s']
    coeff=p['power_coefficients']; joules=(coeff['cruise'][0]*pi+coeff['cruise'][1])*tc+(coeff['takeoff'][0]*pi+coeff['takeoff'][1])*tu+(coeff['landing'][0]*pi+coeff['landing'][1])*td
    e=joules/3_600_000
    if abs(path['energy_kwh']-e)>1e-7: return None,'ENERGY_COEFFICIENT_MISMATCH'
    return {'travel_slots':offset,'energy_kwh':e,'relative_occupancy':occ},None

class PhysicalRuntime(Runtime):
    def evaluate(self,task,ds):
        verify_scenario(task)
        original=self.formal.recompute_path
        self.formal.recompute_path=verify_path
        try: return super().evaluate(task,ds)
        finally: self.formal.recompute_path=original

def verify_scenario(task):
    inst=task['instance']; positions={v['vertiport_id']:v['synthetic_xy_km'] for v in inst['topology']['vertiports']}
    for c in inst['topology']['corridors']:
        if c['geometry_xy_km'][0]!=positions[c['from_vertiport']] or c['geometry_xy_km'][-1]!=positions[c['to_vertiport']]: raise ValueError('corridor endpoint geometry')
        if c['altitude_layer']!='PHYS_25_M': raise ValueError('corridor altitude model')
    for u in inst['fleet']:
        p=u['physical_parameters']; charge=p['charger_input_power_w']*p['charging_efficiency']*inst['slot_min']/60/1000
        if abs(charge-u['charge_kwh_per_block'])>1e-12: raise ValueError('charge power/time units')
        if inst['slot_min']*inst['max_charge_blocks']!=p['max_charge_minutes']: raise ValueError('maximum charge duration')
        if abs(u['reserve_kwh']-u['battery_capacity_kwh']*p['reserve_fraction'])>1e-12: raise ValueError('reserve units')

def ledger(task,ds):
    components,_,rows=event_ledger.ledger(task,ds)
    fleet={u['uav_id']:u for u in task['instance']['fleet']}; cs={c['corridor_id']:c for c in task['instance']['topology']['corridors']}; missions={m['mission_id']:m for m in task['instance']['missions']}
    soc={u:d['initial_soc_kwh'] for u,d in fleet.items()}; soc.update({d['uav_id']:d['initial_soc_kwh'] for d in task['intervention']['initial_soc_overrides']})
    total=0.
    for row in rows:
        if row['held']: continue
        m=missions[row['mission_id']]; u=fleet[row['uav_id']]; path=next(p for p in m['path_options'] if p['path_id']==row['path_id']); e=verify_path(path,m,u,cs)[0]['energy_kwh']; incoming=m.get('incoming_deadhead'); ed=verify_path(incoming,None,u,cs)[0]['energy_kwh'] if incoming else 0.
        s0=soc[row['uav_id']]; arr=s0-ed-e; end=arr+row['charge_blocks']*u['charge_kwh_per_block']; soc[row['uav_id']]=end; total+=e+ed
        row.update(soc_before_incoming_kwh=s0,soc_service_departure_kwh=s0-ed,soc_service_arrival_kwh=arr,soc_after_charge_kwh=end,reserve_margin_kwh=arr-u['reserve_kwh'],incoming_energy_kwh=ed,service_energy_kwh=e,flight_energy_kwh=e+ed,continuous_flight_min=path['travel_time_min_unrounded']+(incoming['travel_time_min_unrounded'] if incoming else 0.))
    components['flight_energy_kwh']=total
    components['continuous_flight_min']=sum(r.get('continuous_flight_min',0) for r in rows)
    return components,rows
