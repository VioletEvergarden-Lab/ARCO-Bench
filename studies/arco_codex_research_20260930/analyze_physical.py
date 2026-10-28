"""References, G, R3 and relevant action/capacity counterfactuals on new tasks."""
import argparse
import copy
from collections import Counter
from common import *
from physical_model import PhysicalRuntime, ledger, power, verify_path

def restricted(rt,task,predicate):
    built=rt.build(task); n=len(built['var_meta'])
    for h in built['hold_idx'].values():
        v=np.zeros(n); v[h]=1; add_row(built,v,0,0)
    banned=np.array([int(m['kind']=='option' and not predicate(m)) for m in built['var_meta']],dtype=float)
    add_row(built,banned,0,0)
    try:
        sol=solve_built(built,'base',task['baseline']); score=rt.evaluate(task,sol['decisions'])
        if not score['formal_feasible']: raise RuntimeError(score)
        return {'status':'OPTIMAL','decisions':sol['decisions'],'objective':score['objective_vector']}
    except RuntimeError as exc:
        if 'infeasible' in str(exc).lower(): return {'status':'INFEASIBLE'}
        raise

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',choices=['pilot','full'],default='pilot'); args=ap.parse_args()
    rt=PhysicalRuntime(); config=read(HERE/'physical/generation_config.json'); meta={r['physical_id']:r for r in config['parents']}; rows=[]; plans=[]; events=[]; occ=[]; paths=[]; relation_rows=[]
    parents=config['parents'][:4 if args.phase=='pilot' else 12]
    for parent in parents:
        rid=parent['physical_id']; path=HERE/'physical/tasks'/f'{rid}.json'
        if not path.exists(): continue
        task=read(path); built=rt.build(task); reference=solve_built(built,'base',task['baseline']); rd=reference['decisions']; rs=rt.evaluate(task,rd)
        if not rs['formal_feasible']: raise RuntimeError((rid,rs))
        g=rt.greedy(task); r3,_=local_repair(rt,task,g); sources={'incumbent':task['baseline']['decisions'],'reference':rd,'G':g,'R3':r3['decisions']}
        source_scores={s:rt.evaluate(task,ds) for s,ds in sources.items()}
        summary={'record_id':rid,'parent_id':parent['parent_id'],'template':parent['metadata']['structural_template_sha256'],'topology':parent['metadata']['coupling_topology'],'mechanism':parent['metadata']['mechanism'],'mission_count':len(rd),'reference_all_served':all(not d['held'] for d in rd),'reference_objective':rs['objective_vector']}
        for s in ('G','R3'):
            score=source_scores[s]; summary[s+'_admissible']=score['formal_feasible']; summary[s+'_quality']=bool(score['formal_feasible'] and quality(score['objective_vector'],rs['objective_vector'])); summary[s+'_served']=sum(not d['held'] for d in sources[s]); summary[s+'_objective']=score['objective_vector']
        base={d['mission_id']:d for d in task['baseline']['decisions']}; mission={m['mission_id']:m for m in task['instance']['missions']}; pair=parent['selected_pair']; target=pair['soc']['uav_id']; soc_mid=pair['soc']['soc_target_mission_id']; target_seq=mission[soc_mid]['sequence_index']
        rules={'pretarget_charge_fixed':lambda o: o['uav_id']!=target or mission[o['mission_id']]['sequence_index']>=target_seq or o['charge_blocks']==base[o['mission_id']]['charge_blocks']}
        if 'FIXED_ROUTES' not in parent['metadata']['mechanism']:
            rules['target_uav_routes_fixed']=lambda o:o['uav_id']!=target or o['path_id']==base[o['mission_id']]['path_id']
        if 'RETIMING' in parent['metadata']['mechanism']:
            rules['target_uav_departures_fixed']=lambda o:o['uav_id']!=target or o['depart_slot']==base[o['mission_id']]['depart_slot']
        for name,predicate in rules.items():
            result=restricted(rt,task,predicate); result.update(record_id=rid,restriction=name)
            result['reference_quality_possible']=result['status']=='OPTIMAL' and quality(result['objective'],rs['objective_vector']); relation_rows.append(result)
        relaxed=copy.deepcopy(task)
        for key in ('pad_capacity_overrides','corridor_capacity_overrides','charger_capacity_overrides'): relaxed['intervention'][key]=[]
        relax=solve_built(rt.build(relaxed),'base',task['baseline']); relax_score=rt.evaluate(relaxed,relax['decisions']); restored=rt.evaluate(task,relax['decisions'])
        if not relax_score['formal_feasible']: raise RuntimeError((rid,relax_score))
        summary['capacity_first_changed_layer']=next((i+1 for i,n in enumerate(TIERS) if abs(rs['objective_vector'][n]-relax_score['objective_vector'][n])>(1e-4 if i==5 else 0)),None)
        summary['relaxed_reference_valid_when_restored']=restored['formal_feasible']
        sources['relaxed_capacity']=relax['decisions']
        for s,ds in sources.items():
            score=rt.evaluate(relaxed if s=='relaxed_capacity' else task,ds)
            plans.append({'record_id':rid,'source':s,'decisions':ds,'objective':score['objective_vector'],'admissible':score['formal_feasible'],'errors':score['formal_error_codes']})
            components,ev=ledger(relaxed if s=='relaxed_capacity' else task,ds)
            events.extend(dict(e,source=s) for e in ev); occ.extend(occupancy(task,ds,s))
        gs,ge=ledger(task,g); fs,fe=ledger(task,rd)
        same_service={d['mission_id'] for d in g if not d['held']}=={d['mission_id'] for d in rd if not d['held']}
        summary['G_reference_same_service']=same_service
        summary['reference_minus_G']={name:fs.get(name,0)-gs.get(name,0) for name in ('departure_after_release_min','charge_duration_min','flight_duration_min','flight_energy_kwh')}
        summary['delay_flight_exchange']=bool(same_service and summary['reference_minus_G']['flight_duration_min']<0 and summary['reference_minus_G']['flight_energy_kwh']<0 and (summary['reference_minus_G']['departure_after_release_min']>0 or summary['reference_minus_G']['charge_duration_min']>0))
        cs={c['corridor_id']:c for c in task['instance']['topology']['corridors']}; fleet={u['uav_id']:u for u in task['instance']['fleet']}
        for m in task['instance']['missions']:
            for p in m['path_options']:
                rec,error=verify_path(p,m,fleet[m['uav_id']],cs)
                if error: raise RuntimeError((rid,m['mission_id'],p['path_id'],error))
                paths.append({'record_id':rid,'mission_id':m['mission_id'],'path_id':p['path_id'],'distance_km':p['distance_km'],'continuous_flight_min':p['travel_time_min_unrounded'],'scheduled_flight_min':p['travel_slots']*5,'rounding_increment_min':p['travel_slots']*5-p['travel_time_min_unrounded'],'cruise_speed_m_s':10,'payload_kg':m['payload_kg'],'cruise_power_w':power(m['payload_kg'],'cruise'),'flight_energy_kwh':rec['energy_kwh'],'segment_count':len(p['corridor_ids'])})
        rows.append(summary); print(rid,'G/R3',summary['G_quality'],summary['R3_quality'],'all served',summary['reference_all_served'],flush=True)
    out=HERE/'physical'; write(out/f'results_{args.phase}.json',rows); csvout(out/f'results_{args.phase}.csv',rows); jsonl(out/f'plans_{args.phase}.jsonl',plans); write(out/f'action_relations_{args.phase}.json',relation_rows)
    csvout(out/f'mission_events_{args.phase}.csv',events); csvout(out/f'resource_events_{args.phase}.csv',occ); csvout(out/f'path_parameters_{args.phase}.csv',paths)
    summary={'tasks':len(rows),'mission_total':sum(r['mission_count'] for r in rows),'reference_all_served':sum(r['reference_all_served'] for r in rows),'G_admissible':sum(r['G_admissible'] for r in rows),'G_quality':sum(r['G_quality'] for r in rows),'R3_admissible':sum(r['R3_admissible'] for r in rows),'R3_quality':sum(r['R3_quality'] for r in rows),'G_served':sum(r['G_served'] for r in rows),'R3_served':sum(r['R3_served'] for r in rows),'capacity_optimum_changed':sum(r['capacity_first_changed_layer'] is not None for r in rows),'G_reference_delay_flight_exchange':sum(r['delay_flight_exchange'] for r in rows),'templates':len({r['template'] for r in rows}),'topologies':len({r['topology'] for r in rows})}
    summary['ranges']={name:[min(r[name] for r in paths),max(r[name] for r in paths)] for name in ('distance_km','continuous_flight_min','scheduled_flight_min','rounding_increment_min','flight_energy_kwh','cruise_power_w')}
    summary['action_relations']={name:{'tests':sum(r['restriction']==name for r in relation_rows),'all_served_infeasible':sum(r['restriction']==name and r['status']=='INFEASIBLE' for r in relation_rows),'quality_possible':sum(r['restriction']==name and r['reference_quality_possible'] for r in relation_rows)} for name in {r['restriction'] for r in relation_rows}}
    write(out/f'summary_{args.phase}.json',summary); print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
