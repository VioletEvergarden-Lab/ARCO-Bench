"""Bounded, structural selection and jointly generated geometry/time/energy tasks."""
import argparse
import copy
import math
from collections import Counter, defaultdict
from common import *
from physical_model import MODEL, PhysicalRuntime, durations, energy, ledger

def choose_parents():
    data=[r for r in read(HERE/'capacity/inputs.json')['rows']]
    groups=sorted({r['metadata']['mechanism'] for r in data})
    chosen=[min((r for r in data if r['metadata']['mechanism']==g),key=lambda r:r['record_id']) for g in groups]
    while len(chosen)<12:
        counts=Counter(r['metadata']['mechanism'] for r in chosen); templates={r['metadata']['structural_template_sha256'] for r in chosen}; topologies={r['metadata']['coupling_topology'] for r in chosen}
        eligible=[r for r in data if r not in chosen and counts[r['metadata']['mechanism']]<3]
        best=min(eligible,key=lambda r:(-int(r['metadata']['structural_template_sha256'] not in templates),-int(r['metadata']['coupling_topology'] not in topologies),r['record_id']))
        chosen.append(best)
    return [{'physical_id':f'ARCO_PHYS_{i:03}','parent_id':r['record_id'],'pilot':i<=4,'metadata':r['metadata'],'selected_pair':r['selected_pair'],'resource':r['resource']} for i,r in enumerate(chosen,1)]

def make_geometry(instance):
    ports=sorted(instance['topology']['vertiports'],key=lambda v:v['vertiport_id']); n=len(ports)
    coords={v['vertiport_id']:[.6*math.cos(2*math.pi*i/n),.6*math.sin(2*math.pi*i/n)] for i,v in enumerate(ports)}
    parallel=defaultdict(list)
    for c in instance['topology']['corridors']: parallel[(c['from_vertiport'],c['to_vertiport'])].append(c)
    for pair,cs in parallel.items():
        a,b=coords[pair[0]],coords[pair[1]]; dx,dy=b[0]-a[0],b[1]-a[1]
        for rank,c in enumerate(sorted(cs,key=lambda c:c['corridor_id'])):
            # Fixed corridor centerlines distinguish parallel resources.
            midpoint=[(a[0]+b[0])/2-.25*rank*dy,(a[1]+b[1])/2+.25*rank*dx]
            points=[a,midpoint,b]; distance=sum(math.dist(x,y) for x,y in zip(points,points[1:]))
            c.update(geometry_xy_km=points,distance_km=distance,base_travel_time_min=distance*1000/MODEL['cruise_speed_m_s']/60,weather_closed=False,no_fly=False,altitude_layer='PHYS_25_M')
    for v in ports: v['synthetic_xy_km']=coords[v['vertiport_id']]

def rebuild_paths(inst):
    cs={c['corridor_id']:c for c in inst['topology']['corridors']}; fleet={u['uav_id']:u for u in inst['fleet']}
    for m in inst['missions']:
        u=fleet[m['uav_id']]
        for path,payload in [(p,m['payload_kg']) for p in m['path_options']]+([(m['incoming_deadhead'],0.)] if m.get('incoming_deadhead') else []):
            seconds=durations(path,u,cs); segs=[]; offset=0
            for cid,t in zip(path['corridor_ids'],seconds):
                slots=math.ceil(t/300)
                segs.append({'corridor_id':cid,'duration_slots':slots,'offset_slot':offset,'wind_level':0}); offset+=slots
            path.update(edge_segments=segs,travel_slots=offset,travel_time_min_unrounded=sum(seconds)/60,distance_km=sum(cs[c]['distance_km'] for c in path['corridor_ids']),energy_kwh=energy(path,payload,u,cs),max_wind_level=0)

def create(rt,parent):
    old=read(P/'data/public/records'/f"{parent['parent_id']}.json"); task=copy.deepcopy(old); rid=parent['physical_id']; task['record_id']=rid
    task['schema_version']='arco_physical_parameter_layer_v1'; task.pop('public_task_sha256',None)
    inst=task['instance']; inst['instance_id']=rid; inst['scenario_id']=rid+'_synthetic_geometry'; inst['physical_model']=copy.deepcopy(MODEL); inst['parent_record_id']=parent['parent_id']
    make_geometry(inst)
    for u in inst['fleet']:
        u.update(physical_parameters=copy.deepcopy(MODEL),uav_type='M100_instrumented_test_configuration',payload_capacity_kg=.5,battery_capacity_kwh=MODEL['battery_capacity_kwh'],reserve_kwh=MODEL['battery_capacity_kwh']*MODEL['reserve_fraction'],initial_soc_kwh=MODEL['battery_capacity_kwh']*MODEL['initial_fraction'],charge_kwh_per_block=MODEL['charger_input_power_w']*MODEL['charging_efficiency']*5/60/1000,available_slot=0,travel_time_coefficient=1.,max_wind_level=0,wind_energy_multiplier_per_level=0.,compatible_layers=['PHYS_25_M'])
    for m in inst['missions']:
        m['payload_kg']=.5 if m['priority']=='urgent' else .25
        m['release_slot']=3*m['sequence_index']; m['due_slot']=m['release_slot']+8
    inst['horizon_slots']=40; rebuild_paths(inst)
    task['intervention']={key:[] for key in ('closed_corridor_slots','corridor_capacity_overrides','pad_capacity_overrides','charger_capacity_overrides','initial_soc_overrides','mission_window_overrides')}
    task['intervention']['instance_id']=rid
    old_b={d['mission_id']:d for d in old['baseline']['decisions']}
    task['baseline']={'decisions':[{'mission_id':m['mission_id'],'uav_id':m['uav_id'],'held':False,'path_id':old_b[m['mission_id']]['path_id'],'depart_slot':m['release_slot'],'charge_blocks':0} for m in inst['missions']]}
    built=rt.build(task)
    for m in inst['missions']:
        mid=m['mission_id']; vector=np.zeros(len(built['var_meta'])); vector[built['hold_idx'][mid]]=1; add_row(built,vector,0,0)
        vector=np.zeros(len(built['var_meta']))
        for i in built['option_indices'][mid]: vector[i]=int(built['var_meta'][i]['path_id']!=old_b[mid]['path_id'])
        add_row(built,vector,0,0)
    incumbent=solve_built(built,'base',task['baseline'])['decisions']; task['baseline']={'decisions':incumbent}
    _,ev=ledger(task,incumbent); by_mid={e['mission_id']:e for e in ev}
    for m in inst['missions']:
        e=by_mid[m['mission_id']]; m['release_slot']=max(0,e['depart_slot']-1); m['due_slot']=e['arrival_slot']+(1 if m['priority']=='urgent' else 3)
    inst['horizon_slots']=max(e['completion_slot'] for e in ev)+20
    pre=rt.evaluate(task,incumbent)
    if not pre['formal_feasible']: raise RuntimeError(('incumbent',pre))
    inter=task['intervention']; pair=parent['selected_pair']; target_uav=pair['soc']['uav_id']
    target_chain=sorted([e for e in ev if e['uav_id']==target_uav],key=lambda e:e['depart_slot'])
    first=target_chain[0]['flight_energy_kwh']; remaining=sum(e['flight_energy_kwh'] for e in target_chain[1:])
    reserve=next(u['reserve_kwh'] for u in inst['fleet'] if u['uav_id']==target_uav)
    inter['initial_soc_overrides']=[{'uav_id':target_uav,'initial_soc_kwh':reserve+first+.5*remaining}]
    old_closed=sorted({r['corridor_id'] for r in old['intervention']['closed_corridor_slots']})
    uses=occupancy(task,incumbent,'incumbent')
    for cid in old_closed:
        slots=[e['slot'] for e in uses if e['kind']=='corridor' and e['resource']==cid]
        if slots:
            start=min(slots); inter['closed_corridor_slots'].extend({'corridor_id':cid,'slot':t} for t in range(start,start+3))
    resource=parent['resource']; uses_r=[e for e in uses if e['kind']==resource['kind'] and e['resource']==resource['node']]
    if uses_r:
        counts=Counter(e['slot'] for e in uses_r); slot=min(counts,key=lambda t:(-counts[t],t)); key=resource['kind']+'_capacity_overrides'; field='corridor_id' if resource['kind']=='corridor' else 'vertiport_id'
        inter[key]=[{field:resource['node'],'slot':slot,'capacity':1}]
    inst.pop('instance_sha256',None); inst['instance_sha256']=rt.core.sha256_obj(inst)
    post=rt.evaluate(task,incumbent)
    return task,{'record_id':rid,'parent_id':parent['parent_id'],'incumbent_pre_disruption_valid':pre['formal_feasible'],'incumbent_post_disruption_valid':post['formal_feasible'],'post_disruption_errors':post['formal_error_codes'],'mapped_resource':resource,'selection_metadata':parent['metadata'],'selected_pair':pair,'generation_attempt':1,'disruption_rule':'half of remaining chain flight energy after first flight; original closed corridors for 3 slots from first incumbent use; selected resource at maximum incumbent occupancy'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',choices=['pilot','full'],default='pilot'); args=ap.parse_args()
    out=HERE/'physical'; out.mkdir(exist_ok=True)
    config_path=out/'generation_config.json'
    if not config_path.exists():
        parents=choose_parents(); write(config_path,{'model':MODEL,'geometry':'radius 0.6 km regular polygon; parallel corridor midpoint offset 0.25 times chord times rank','parent_selection':'minimum ID per action group; then maximize previously unrepresented template and topology subject to 3/group; independent of model outcomes','maximum_attempts_per_parent':1,'parents':parents})
    config=read(config_path); rt=PhysicalRuntime(); outcomes=[]
    for parent in config['parents'][:4 if args.phase=='pilot' else 12]:
        try:
            task,meta=create(rt,parent); write(out/'tasks'/f"{task['record_id']}.json",task); outcomes.append(meta)
            print(task['record_id'],parent['parent_id'],meta['post_disruption_errors'],flush=True)
        except Exception as exc:
            outcomes.append({'record_id':parent['physical_id'],'parent_id':parent['parent_id'],'generation_attempt':1,'generation_failed':str(exc)}); print(parent['physical_id'],'FAILED',exc,flush=True)
    write(out/f'generation_{args.phase}.json',outcomes)

if __name__=='__main__': main()
