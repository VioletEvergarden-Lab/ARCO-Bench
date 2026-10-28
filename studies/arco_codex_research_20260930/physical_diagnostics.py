"""Selected competitor relations and the two remaining physical R3 gaps."""
from common import *
from physical_model import PhysicalRuntime, ledger

def main():
    rt=PhysicalRuntime(); inputs={r['record_id']:r for r in read(HERE/'capacity/inputs.json')['rows']}; parents=read(HERE/'physical/generation_config.json')['parents']
    results=read(HERE/'physical/results_full.json'); plans={(r['record_id'],r['source']):r['decisions'] for r in jl(HERE/'physical/plans_full.jsonl')}
    cases=[]; competitors=[]; events=[]; resources=[]
    for parent,row in zip(parents,results):
        rid=parent['physical_id']; task=read(HERE/'physical/tasks'/f'{rid}.json'); ref=row['reference_objective']; rd=plans[rid,'reference']
        if not row['R3_quality']:
            built=rt.build(task); vs=dict(built['tiers'])
            for name in TIERS[:5]: add_row(built,vs[name],ref[name],ref[name])
            add_row(built,vs[TIERS[-1]],ref[TIERS[-1]]-1e-4-.5e-6+1e-9,ref[TIERS[-1]]+1e-4+.5e-6-1e-9)
            match=match_vector(built,plans[rid,'G']); result=optimize(built,-match); ds=extract(built,result.x); score=rt.evaluate(task,ds)
            if not score['formal_feasible'] or not quality(score['objective_vector'],ref): raise RuntimeError(score)
            cases.append({'record_id':rid,'k_star':len(ds)-int(round(np.dot(match,result.x))),'changed_missions':diff(plans[rid,'G'],ds),'affected_uavs':sorted({d['uav_id'] for d in ds if d['mission_id'] in diff(plans[rid,'G'],ds)}),'decisions':ds,'objective':score['objective_vector'],'mip_gap':float(result.mip_gap or 0)})
        definition=inputs[parent['parent_id']]['competitor_definition']; mid=definition['mission_id']; mission=next(m for m in task['instance']['missions'] if m['mission_id']==mid); dref=next(d for d in rd if d['mission_id']==mid); refpath=next(p for p in mission['path_options'] if p['path_id']==dref['path_id'])
        for prefix in (True,False):
            built=rt.build(task); n=len(built['var_meta']); vec=np.zeros(n)
            equivalents={p['path_id'] for p in mission['path_options'] if p['corridor_ids']==refpath['corridor_ids']}
            for i in built['option_indices'][mid]: vec[i]=int(built['var_meta'][i]['path_id'] in equivalents)
            vec[built['hold_idx'][mid]]=1; add_row(built,vec,0,0)
            vec=np.zeros(n)
            for h in built['hold_idx'].values(): vec[h]=1
            add_row(built,vec,0,0)
            if prefix:
                for name,v in built['tiers'][:TIERS.index(definition['target_tier'])]: add_row(built,v,ref[name],ref[name])
            try: sol=solve_built(built,'base',task['baseline'])
            except RuntimeError as exc:
                if 'infeasible' not in str(exc).lower(): raise
                competitors.append({'record_id':rid,'parent_id':parent['parent_id'],'prefix_preserved':prefix,'mission_id':mid,'tier':definition['target_tier'],'status':'INFEASIBLE'}); continue
            ds=sol['decisions']; score=rt.evaluate(task,ds)
            if not score['formal_feasible']: raise RuntimeError(score)
            a,_=ledger(task,rd); b,ev=ledger(task,ds)
            delta={k:b.get(k,0)-a.get(k,0) for k in ('departure_after_release_min','charge_duration_min','flight_duration_min','continuous_flight_min','flight_energy_kwh')}
            exchange=delta['flight_duration_min']<0 and delta['flight_energy_kwh']<0 and (delta['departure_after_release_min']>0 or delta['charge_duration_min']>0)
            source='prefix_competitor' if prefix else 'route_distinct_competitor'
            continuous_exchange=delta['continuous_flight_min']<0 and delta['flight_energy_kwh']<0 and (delta['departure_after_release_min']>0 or delta['charge_duration_min']>0)
            competitors.append({'record_id':rid,'parent_id':parent['parent_id'],'prefix_preserved':prefix,'mission_id':mid,'tier':definition['target_tier'],'status':'OPTIMAL','objective':score['objective_vector'],'delta_from_reference':delta,'delay_flight_exchange':exchange,'continuous_delay_flight_exchange':continuous_exchange,'decisions':ds})
            events.extend(dict(e,source=source) for e in ev); resources.extend(occupancy(task,ds,source))
    out=HERE/'physical'; write(out/'coordination_gaps.json',cases); write(out/'competitor_relations.json',competitors); csvout(out/'competitor_relations.csv',competitors)
    csvout(out/'competitor_events.csv',events); csvout(out/'competitor_resource_events.csv',resources)
    print('Minimum physical distances:',[(r['record_id'],r['k_star']) for r in cases]); print('Prefix competitors feasible:',sum(r['prefix_preserved'] and r['status']=='OPTIMAL' for r in competitors)); print('Scheduled delay/flight exchange:',sum(r.get('delay_flight_exchange',False) for r in competitors)); print('Continuous delay/flight exchange:',sum(r.get('continuous_delay_flight_exchange',False) for r in competitors))

if __name__=='__main__': main()
