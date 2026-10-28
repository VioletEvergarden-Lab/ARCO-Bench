"""Compare objective priorities and classify restricted diagnostics."""
import argparse
from collections import defaultdict
from itertools import combinations
from mechanism_metrics import read, write, csvout, metrics
from preference_solver import ROOT, OLD, Engine, TIERS, QUALITY_TOL, ORDER

def resource_changes(oldscore,newscore):
    def groups(score):
        out=defaultdict(dict)
        for r in score['resource_intervals']:
            key=(r['kind'],r['resource']); mid=r['mission_id']
            if mid not in out[key] or r['start_min']<out[key][mid][0]: out[key][mid]=(r['start_min'],r['uav_id'])
        return out
    old,new=groups(oldscore),groups(newscore); reversed_pairs=[]; access=[]
    for key in sorted(set(old)|set(new)):
        before,after=old.get(key,{}),new.get(key,{})
        if set(before)!=set(after): access.append({'kind':key[0],'resource':key[1],'removed':sorted(set(before)-set(after)),'added':sorted(set(after)-set(before))})
        for a,b in combinations(sorted(set(before)&set(after)),2):
            if before[a][1]==before[b][1]: continue
            if (before[a][0]-before[b][0])*(after[a][0]-after[b][0]) < -1e-9:
                reversed_pairs.append({'kind':key[0],'resource':key[1],'missions':[a,b],'original_start_min':[before[a][0],before[b][0]],'preference_start_min':[after[a][0],after[b][0]]})
    return reversed_pairs,access

def analyze(partial=False,select=False):
    comparisons=[]; candidate_rows=[]; events=[]
    historical=[r for r in read(OLD/'evaluation/scores.json') if r['layer']=='network' and r['source'] in ('deepseek','luna')]
    for path in sorted((ROOT/'results/preference/references').glob('NET_*.json')):
        new=read(path); task=read(OLD/'networks/tasks'/path.name); old=read(OLD/'networks/references'/path.name); rid=path.stem; eng=Engine(task)
        a=metrics(task,old['decisions'],old,'original_reference'); b=metrics(task,new['decisions'],new,'preference_reference',ORDER) if new['decisions'] else None
        if b is None:
            comparisons.append({'record_id':rid,'status':new['status'],'optimal':False,'proved_prefix':new['proved_prefix']}); continue
        d1={d['mission_id']:d for d in old['decisions']}; d2={d['mission_id']:d for d in new['decisions']}
        route_changed=[mid for mid in d1 if not d1[mid]['held'] and not d2[mid]['held'] and d1[mid]['path_id']!=d2[mid]['path_id']]
        added_detours=[mid for mid in route_changed if d1[mid]['path_id']==eng.base[mid]['path_id'] and d2[mid]['path_id']!=eng.base[mid]['path_id']]
        waiting_to_detour=[mid for mid in added_detours if d1[mid]['depart_min']>eng.base[mid]['depart_min']+1e-7]
        charging=[mid for mid in d1 if not d1[mid]['held'] and not d2[mid]['held'] and d1[mid]['charge_blocks']!=d2[mid]['charge_blocks']]
        oldscore,newscore=eng.verify(old['decisions']),eng.verify(new['decisions'])
        reversals,access=resource_changes(oldscore,newscore)
        row={'record_id':rid,'scale':rid.split('_')[1][0],'condition':rid[-1], 'status':new['status'],'optimal':new['optimal'],'proved_prefix':new['proved_prefix'],
             'original_objective':old['objective'],'preference_objective':new['objective'],'route_decisions_changed':route_changed,'added_detour_missions':added_detours,'waiting_to_detour_missions':waiting_to_detour,
             'charge_decisions_changed':charging,'resource_order_reversals':reversals,'resource_access_changes':access,
             'same_service_set':a['served_missions']==b['served_missions'],
             'delta_urgent_on_time':b['urgent_on_time']-a['urgent_on_time'],'delta_total_on_time':b['total_on_time']-a['total_on_time'],
             'delta_weighted_tardiness_min':b['weighted_tardiness_min']-a['weighted_tardiness_min'],
             'delta_flight_energy_kwh':b['flight_energy_kwh']-a['flight_energy_kwh'],'delta_charge_blocks':b['charge_blocks']-a['charge_blocks']}
        for field in ('urgent_demand','urgent_served','urgent_on_time','total_served','total_on_time','route_changes','charge_changes','charge_blocks','departure_changes','flight_energy_kwh','minimum_postflight_reserve_margin_kwh'):
            row['original_'+field]=a[field]; row['preference_'+field]=b[field]
        comparisons.append(row); candidate_rows.extend([a,b])
        for r in historical:
            if r['record_id']!=rid: continue
            if r.get('decisions') is not None:
                fixed=metrics(task,r['decisions'],new,'fixed_'+r['source'],ORDER)
            else:
                fixed={'record_id':rid,'source':'fixed_'+r['source'],'admissible':False,'status':r['status'],'errors':r['errors']}
            fixed['preference_reference_certified']=new['optimal']; fixed['analysis_type']='fixed archived output; no preference regeneration'; candidate_rows.append(fixed)
        for label,score in [('original',oldscore),('preference',newscore)]:
            events.extend(dict(e,record_id=rid,objective_setting=label) for e in score['events'])
    out=ROOT/'results/preference'
    write(out/'comparison.json',comparisons); csvout(out/'comparison.csv',comparisons); csvout(out/'candidate_metrics.csv',candidate_rows); write(out/'candidate_metrics.json',candidate_rows); csvout(out/'events.csv',events)
    if select:
        assert len(comparisons)==36, 'Freeze restriction selection only after all 36 attempted references exist.'
        selected=[]
        for scale in 'SML':
            subset=[r for r in comparisons if r.get('optimal') and r.get('scale')==scale]
            routes=sorted([r for r in subset if r['route_decisions_changed']],key=lambda r:('ABC'.index(r['condition']),r['record_id']))
            if routes: selected.append({'record_id':routes[0]['record_id'],'selection_type':'service-route decision changes','scale':scale,'condition':routes[0]['condition']})
            punctual=sorted([r for r in subset if r['delta_urgent_on_time']!=0 and r['record_id'] not in {x['record_id'] for x in selected}],key=lambda r:('BCA'.index(r['condition']),r['record_id']))
            if punctual: selected.append({'record_id':punctual[0]['record_id'],'selection_type':'urgent on-time count changes','scale':scale,'condition':punctual[0]['condition']})
        write(ROOT/'protocol/preference_restriction_selection.json',{'protocol':'preference_protocol.json','selected':selected})
    restricted=[]
    for path in sorted((out/'restrictions').glob('*.json')):
        r=read(path); reference=read(out/'references'/f"{r['record_id']}.json")
        classification='unknown'; evidence='no conclusive bound'
        if r['status']=='infeasible': classification='necessary_for_optimal_service'; evidence='fixed-service model proven infeasible'
        else:
            for phase in r['phases']:
                tier=phase['tier']; j=TIERS.index(tier); target=reference['objective'][tier]
                if phase['lower_bound'] is not None and phase['lower_bound']>target+QUALITY_TOL[j]+1e-9:
                    classification='necessary_for_preference_quality'; evidence=f"{tier} lower bound {phase['lower_bound']:.12g} exceeds target {target:.12g}"; break
                if phase['status']!=0: break
            if classification=='unknown' and r['objective'] is not None and all(abs(r['objective'][tier]-reference['objective'][tier])<=QUALITY_TOL[j]+1e-10 for j,tier in enumerate(TIERS)):
                classification='not_necessary_for_reference_quality'; evidence='admissible equal-quality witness'
        restricted.append({'record_id':r['record_id'],'restriction':r['restriction'],'status':r['status'],'optimal':r['optimal'],'proved_prefix':r['proved_prefix'],'classification':classification,'evidence':evidence,'objective':r['objective'],'phases':r['phases']})
    write(out/'restriction_summary.json',restricted); csvout(out/'restriction_summary.csv',restricted)
    summary={'tasks_attempted':len(comparisons),'fully_certified':sum(r['optimal'] for r in comparisons),
             'tasks_with_route_decision_changes':sum(bool(r.get('route_decisions_changed')) for r in comparisons),
             'tasks_waiting_to_detour':sum(bool(r.get('waiting_to_detour_missions')) for r in comparisons),
             'tasks_with_charge_changes':sum(bool(r.get('charge_decisions_changed')) for r in comparisons),
             'tasks_with_resource_order_reversals':sum(bool(r.get('resource_order_reversals')) for r in comparisons),
             'original_route_changes':sum(r.get('original_route_changes',0) for r in comparisons),'preference_route_changes':sum(r.get('preference_route_changes',0) for r in comparisons),
             'original_urgent_on_time':sum(r.get('original_urgent_on_time',0) for r in comparisons),'preference_urgent_on_time':sum(r.get('preference_urgent_on_time',0) for r in comparisons),
             'delta_weighted_tardiness_min':sum(r.get('delta_weighted_tardiness_min',0) for r in comparisons),
             'restriction_count':len(restricted),'unknown_restrictions':sum(r['classification']=='unknown' for r in restricted)}
    same=[r for r in comparisons if r.get('same_service_set')]
    summary.update(same_service_set_tasks=len(same),same_service_original_energy_kwh=sum(r['original_flight_energy_kwh'] for r in same),same_service_preference_energy_kwh=sum(r['preference_flight_energy_kwh'] for r in same),
                   original_weighted_tardiness_min=sum(r.get('original_objective',{}).get(TIERS[3],0) for r in comparisons),preference_weighted_tardiness_min=sum(r.get('preference_objective',{}).get(TIERS[3],0) for r in comparisons),
                   original_charge_blocks=sum(r.get('original_charge_blocks',0) for r in comparisons),preference_charge_blocks=sum(r.get('preference_charge_blocks',0) for r in comparisons))
    summary['fixed_candidate_analysis']={s:{'attempts':sum(r['source']=='fixed_'+s for r in candidate_rows),'admissible':sum(r['source']=='fixed_'+s and r['admissible'] for r in candidate_rows),'reference_quality':sum(r['source']=='fixed_'+s and r.get('reference_quality',False) for r in candidate_rows)} for s in ('deepseek','luna')}
    write(out/'summary.json',summary); print(summary)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--partial',action='store_true'); p.add_argument('--select',action='store_true'); args=p.parse_args(); analyze(args.partial,args.select)
