"""Keep the 12 existing physical scenes and their calendars; change event time only."""
import copy
import json
from study_common import *
from continuous_engine import Engine,flight,quality,buckets,overlap

def convert(old):
    inst=old['instance']; model=copy.deepcopy(inst['physical_model'])
    task={'record_id':'BRIDGE_'+old['record_id'],'schema_version':'arco_continuous_events_v1','model':model,'timing':{'departure_grid_min':5,'resource_window_min':5,'charge_block_min':5,'max_charge_blocks':3,'turnaround_min':5,'horizon_departure_min':inst['horizon_slots']*5},'nodes':[{'vertiport_id':v['vertiport_id'],'xy_km':v['synthetic_xy_km']} for v in inst['topology']['vertiports']],'corridors':[{'corridor_id':c['corridor_id'],'origin':c['from_vertiport'],'destination':c['to_vertiport'],'distance_km':c['distance_km'],'geometry_xy_km':c['geometry_xy_km']} for c in inst['topology']['corridors']],'fleet':[],'missions':[],'resources':{'corridor':inst['resources']['corridor_capacity_by_slot_default'],'pad':inst['resources']['pad_capacity_by_slot_default'],'charger':inst['resources']['charger_capacity_by_slot_default']},'baseline':{'decisions':[]},'intervention':{'resource_intervals':[],'initial_soc_overrides':{r['uav_id']:r['initial_soc_kwh'] for r in old['intervention']['initial_soc_overrides']}}}
    def path(p,origin,destination): return {'path_id':p['path_id'],'origin':origin,'destination':destination,'corridor_ids':p['corridor_ids'],'flight_min':p['travel_time_min_unrounded'],'energy_kwh':p['energy_kwh']}
    for m in inst['missions']:
        new={'mission_id':m['mission_id'],'uav_id':m['uav_id'],'sequence_index':m['sequence_index'],'origin':m['origin_vertiport'],'destination':m['destination_vertiport'],'payload_kg':m['payload_kg'],'priority':m['priority'],'release_min':m['release_slot']*5,'due_min':m['due_slot']*5,'paths':[path(p,m['origin_vertiport'],m['destination_vertiport']) for p in m['path_options']],'incoming':path(m['incoming_deadhead'],m['incoming_deadhead']['node_sequence'][0],m['origin_vertiport']) if m.get('incoming_deadhead') else None}
        task['missions'].append(new)
    for u in inst['fleet']:
        first=min((m for m in task['missions'] if m['uav_id']==u['uav_id']),key=lambda m:m['sequence_index'])
        task['fleet'].append({k:u[k] for k in ('uav_id','initial_soc_kwh','battery_capacity_kwh','reserve_kwh')}|{'available_min':u['available_slot']*5,'initial_vertiport':first['origin']})
    for d in old['baseline']['decisions']: task['baseline']['decisions'].append({k:d[k] for k in ('mission_id','uav_id','held','path_id','charge_blocks')}|{'depart_min':None if d['held'] else d['depart_slot']*5})
    for r in old['intervention']['closed_corridor_slots']: task['intervention']['resource_intervals'].append({'kind':'corridor','resource':r['corridor_id'],'start_min':r['slot']*5,'end_min':(r['slot']+1)*5,'capacity':0})
    for kind,key in [('corridor','corridor_capacity_overrides'),('pad','pad_capacity_overrides'),('charger','charger_capacity_overrides')]:
        for r in old['intervention'][key]: task['intervention']['resource_intervals'].append({'kind':kind,'resource':r.get('corridor_id',r.get('vertiport_id')),'start_min':r['slot']*5,'end_min':(r['slot']+1)*5,'capacity':r['capacity']})
    return task

def checks(task):
    assert list(buckets(1,2,1))==[1] and not overlap(0,1,1,2)
    # A multi-segment arrival is the sum of physical segment times, independently
    # of five-minute resource cover. No takeoff/landing is added in the middle.
    m=next(m for m in task['missions'] if any(len(p['corridor_ids'])>1 for p in m['paths']))
    p=next(p for p in m['paths'] if len(p['corridor_ids'])>1); f=flight(task,p,m['payload_kg'])
    assert abs(f['intervals'][-1][-1]-f['flight_min'])<1e-10
    # A charge after an under-reserve arrival cannot repair that flight's legality.
    single=copy.deepcopy(task); single['record_id']='CHECK_RESERVE_ORDER'; single['missions']=[copy.deepcopy(m)]
    single['missions'][0]['incoming']=None; single['missions'][0]['sequence_index']=1; single['missions'][0]['release_min']=0
    uid=m['uav_id']; u=copy.deepcopy(next(u for u in task['fleet'] if u['uav_id']==uid)); u['initial_vertiport']=m['origin']; u['available_min']=0; u['initial_soc_kwh']=u['reserve_kwh']+f['energy_kwh']*.5; single['fleet']=[u]
    single['intervention']={'resource_intervals':[],'initial_soc_overrides':{}}
    d={'mission_id':m['mission_id'],'uav_id':uid,'held':False,'path_id':p['path_id'],'depart_min':0,'charge_blocks':3}; single['baseline']={'decisions':[d]}
    score=Engine(single).verify([d]); assert 'SOC_RESERVE_BEFORE_CHARGE' in score['errors']
    return {'multisegment_time':True,'half_open_boundary':True,'reserve_before_charge':True}

def main():
    out=HERE/'semantic_bridge'; rows=[]; plans=[]; events=[]; relations=[]
    parents={r['physical_id']:r for r in read(R30/'physical/generation_config.json')['parents']}
    for path in sorted((R30/'physical/tasks').glob('ARCO_PHYS_*.json')):
        old=read(path); task=convert(old); rid=task['record_id']; pre=copy.deepcopy(task); pre['intervention']={'resource_intervals':[],'initial_soc_overrides':{}}
        eng=Engine(task); pre_eng=Engine(pre); before=pre_eng.verify(task['baseline']['decisions']); after=eng.verify(task['baseline']['decisions']); reference=eng.solve(budget=180)
        if not reference['optimal']: raise RuntimeError((rid,'bridge reference',reference['phases']))
        g=eng.greedy(); gscore=eng.verify(g); local=eng.solve(g,4,budget=180)
        row={'record_id':rid,'parent_id':parents[old['record_id']]['parent_id'],'old_incumbent_pre_valid':before['admissible'],'pre_errors':before['errors'],'old_incumbent_post_valid':after['admissible'],'post_errors':after['errors'],'reference':reference['objective'],'G_quality':gscore['admissible'] and quality(gscore['objective'],reference['objective']),'R4_quality':local['optimal'] and quality(local['objective'],reference['objective'])}; rows.append(row)
        if not before['admissible']:
            recovery=pre_eng.solve(all_served=True,budget=180)
            plans.append({'record_id':rid,'source':'separately_repaired_pre_incumbent','result':recovery})
        for source,ds in [('original_incumbent',task['baseline']['decisions']),('reference',reference['decisions']),('G',g),('R4',local['decisions'])]:
            scored=eng.verify(ds); plans.append({'record_id':rid,'source':source,'decisions':ds,'score':scored}); events.extend(dict(e,source=source) for e in scored['events'])
        meta=parents[old['record_id']]; pair=meta['selected_pair']; uid=pair['soc']['uav_id']; target=next(m['sequence_index'] for m in task['missions'] if m['mission_id']==pair['soc']['soc_target_mission_id']); base=eng.base
        rules={'pretarget_charge_fixed':lambda o:o['uav_id']!=uid or eng.missions[o['mission_id']]['sequence_index']>=target or o['charge_blocks']==base[o['mission_id']]['charge_blocks']}
        if 'FIXED_ROUTES' not in meta['metadata']['mechanism']: rules['target_routes_fixed']=lambda o:o['uav_id']!=uid or o['path_id']==base[o['mission_id']]['path_id']
        if 'RETIMING' in meta['metadata']['mechanism']: rules['target_departures_fixed']=lambda o:o['uav_id']!=uid or o['depart_min']==base[o['mission_id']]['depart_min']
        for name,rule in rules.items():
            result=eng.solve(all_served=True,budget=180,allowed=rule); relations.append({'record_id':rid,'restriction':name,'all_service_feasible':result['decisions'] is not None,'reference_quality_possible':result['optimal'] and quality(result['objective'],reference['objective']),'result':result})
        write(out/'tasks'/f'{rid}.json',task); write(out/'references'/f'{rid}.json',reference)
        print(rid,'incumbent pre',before['admissible'],'G/R4',row['G_quality'],row['R4_quality'],flush=True)
    write(out/'results.json',rows); csvout(out/'results.csv',rows); jsonl(out/'plans.jsonl',plans); csvout(out/'events.csv',events); write(out/'relations.json',relations)
    write(out/'checks.json',checks(convert(read(R30/'physical/tasks/ARCO_PHYS_001.json'))))

if __name__=='__main__': main()
