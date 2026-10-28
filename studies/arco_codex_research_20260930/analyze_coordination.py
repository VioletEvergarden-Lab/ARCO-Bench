"""Minimum mission-decision distance from G to the public reference-quality set."""
from collections import Counter
from common import *

IDS=[f'CA12_CORE_{n:03}' for n in (23,28,34,38,45,49,51,56,57,61,65,70,71,72)]

def main():
    rt=Runtime(); seeds=decisions(R/'policy_domains/public_both.jsonl'); repairs=decisions(R/'local_repair/responses.jsonl')
    refs={r['record_id']:r for r in jl(P/'references/public_domain.jsonl')}
    rows=[]; plans=[]; events=[]; resources=[]
    for rid in IDS:
        task=read(P/'data/public/records'/f'{rid}.json'); built=rt.build(task)
        ref=refs[rid]['objective']; vectors=dict(built['tiers'])
        for name in TIERS[:5]: add_row(built,vectors[name],ref[name],ref[name])
        # The public evaluator rounds energy to 6 decimals. Include precisely
        # the rounding cells accepted by the 1e-4 final-tier tolerance.
        half_cell=0.5e-6-1e-9
        add_row(built,vectors[TIERS[-1]],ref[TIERS[-1]]-1e-4-half_cell,ref[TIERS[-1]]+1e-4+half_cell)
        matches=match_vector(built,seeds[rid]); optimum=optimize(built,-matches)
        k=len(seeds[rid])-int(round(np.dot(matches,optimum.x)))
        add_row(built,matches,len(seeds[rid])-k,len(seeds[rid])-k)
        representative=optimize(built,vectors[TIERS[-1]])
        ds=extract(built,representative.x); score=rt.evaluate(task,ds)
        if not score['formal_feasible'] or not quality(score['objective_vector'],ref): raise RuntimeError((rid,score))
        changed=diff(seeds[rid],ds)
        if len(changed)!=k: raise RuntimeError((rid,k,changed))
        r3obj=objective(task,repairs[rid],'base')
        first=next((i+1 for i,n in enumerate(TIERS) if abs(r3obj[n]-ref[n])>(1e-4 if i==5 else 0)),None)
        if k<=3: raise RuntimeError(('R3 discrepancy requires investigation',rid,k))
        uavs=sorted({d['uav_id'] for d in ds if d['mission_id'] in changed})
        shared=[{'kind':kind,'resource':x.get('vertiport_id',x.get('corridor_id')),'slot':x['slot'],'capacity':x['capacity']} for kind,key in (('pad','pad_capacity_overrides'),('corridor','corridor_capacity_overrides'),('charger','charger_capacity_overrides')) for x in task['intervention'][key]]
        rows.append({'task':rid,'mission_count':len(ds),'R3_first_mismatch_layer':first,'k_star':k,'changed_missions':changed,'affected_uavs':uavs,'shared_resource':shared,'all_served':all(not d['held'] for d in ds),'archived_reference_distance':len(diff(seeds[rid],refs[rid]['decisions'])),'G_objective':objective(task,seeds[rid],'base'),'R3_objective':r3obj,'nearest_quality_objective':score['objective_vector'],'mip_gap':float(optimum.mip_gap or 0),'distance_lower_bound':len(ds)+float(optimum.mip_dual_bound)})
        plans.append({'record_id':rid,'k_star':k,'decisions':ds,'objective':score['objective_vector']})
        for name,dec in [('G',seeds[rid]),('R3',repairs[rid]),('nearest_quality',ds)]:
            _,_,ev=event_ledger.ledger(task,dec); events.extend(dict(e,source=name) for e in ev)
            resources.extend(occupancy(task,dec,name))
        print(rid,k,','.join(uavs),flush=True)
    out=HERE/'coordination'; csvout(out/'coordination_distance.csv',rows); write(out/'results.json',rows)
    jsonl(out/'nearest_quality.jsonl',plans); csvout(out/'mission_events.csv',events); csvout(out/'resource_events.csv',resources)
    summary={'tasks':len(rows),'k_star_distribution':dict(sorted(Counter(r['k_star'] for r in rows).items())),'affected_uav_distribution':dict(Counter(len(r['affected_uavs']) for r in rows)),'all_minima_above_three':all(r['k_star']>3 for r in rows),'case_ids':['CA12_CORE_034','CA12_CORE_051']}
    write(out/'summary.json',summary); print(json.dumps(summary))

if __name__=='__main__': main()
