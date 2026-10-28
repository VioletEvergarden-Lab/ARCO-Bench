"""Reconstruct parallel-arrival selection from independent, verified traces.

No model requests or optimization are performed. All plotted clock values are
end-to-end source availability plus measured comparator/selection overhead,
never the selector's short processing time on its own.
"""
from pathlib import Path
import argparse
import json
import time
from collections import Counter
from optimization_online import TIERS, compare, quality
from optimization_summary import csvout

ROOT=Path(__file__).resolve().parents[1]
BUDGETS=(30,60,180,300,600)
DETERMINISTIC=('G','R4','Full-MILP','Iter-R4','R_frac')
PROVIDERS=('deepseek','luna')
SCOPE='reconstructed parallel-arrival selection from independently timed source traces'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def replay(arrivals):
    """One serial selector, stable arrival order, public tolerance comparator."""
    deliveries=[];events=[];selected=None;free_at=0.
    ordered=sorted(arrivals,key=lambda e:(e['available_seconds'],e.get('tie_priority',0),e.get('sequence',0)))
    for proposal in ordered:
        arrival=float(proposal['available_seconds'])
        begin=max(arrival,free_at)
        clock=time.perf_counter_ns()
        changed=selected is None or compare(proposal['objective'],selected['objective'])<0
        if changed:
            selected=proposal
        overhead=(time.perf_counter_ns()-clock)/1e9
        free_at=begin+overhead
        event={'source':proposal['source'],'source_available_seconds':arrival,
               'selector_start_seconds':begin,'comparison_selection_seconds':overhead,
               'selector_finish_seconds':free_at,'strict_update':changed,
               'selected_source':selected['source'],'selected_objective':selected['objective'],
               'proposal_objective':proposal['objective']}
        events.append(event)
        if changed:
            deliveries.append({**selected,'available_seconds':free_at,
                               'source_available_seconds':selected['available_seconds']})
    return deliveries,events


def at(events,cutoff):
    reached=[e for e in events if e['available_seconds']<=cutoff]
    return reached[-1] if reached else None


def candidate_fields(candidate,reference,urgent,total):
    objective=candidate['objective'] if candidate else None
    certified=bool(reference.get('optimal') or reference.get('global_optimal'))
    prefix=6 if certified else int(reference.get('proved_prefix',0))
    rv=reference.get('objective')
    metrics=candidate.get('metrics',{}) if candidate else {}
    return {'admissible':candidate is not None,
            'reference_certified':certified,'reference_service_certified':prefix>=2,
            'service_target':bool(objective and rv and prefix>=2 and all(abs(objective[k]-rv[k])<=1e-9 for k in TIERS[:2])),
            'reference_quality':bool(objective and rv and certified and quality(objective,rv)),
            'urgent_served':urgent-int(objective[TIERS[0]]) if objective else None,
            'total_served':total-int(objective[TIERS[1]]) if objective else None,
            'urgent_on_time':metrics.get('urgent_on_time'),
            'total_on_time':metrics.get('total_on_time'),
            'selected_source':candidate['source'] if candidate else None,
            'selected_available_seconds':candidate['available_seconds'] if candidate else None,
            'objective':objective}


def retain_pending(row,complete):
    """Publish known delivered plans without relabeling pending runs as fails."""
    row['analysis_complete']=complete
    for key in ('admissible','service_target','reference_quality'):
        row['known_'+key]=row[key]
        if not complete:
            row[key]=None
    return row


def load_deterministic(path,method):
    if not path.exists():
        return {'complete':False,'status':'pending','arrivals':[]}
    result=read(path)
    arrivals=[]
    for i,e in enumerate(result['improvements']):
        if not e.get('admissible',True) or not e.get('within_budget',True):
            continue
        arrivals.append({'source':method,'sequence':i,'tie_priority':0,
                         'available_seconds':e['available_seconds'],'objective':e['objective'],
                         'metrics':{k:e.get(k) for k in ('urgent_on_time','total_on_time')}})
    return {'complete':True,'status':result.get('stop_reason','completed'),'arrivals':arrivals}


def load_model(path,provider):
    if not path.exists():
        return {'complete':False,'status':'pending','arrivals':[]}
    result=read(path)
    available=result.get('available_seconds')
    admissible=result.get('admissible',False)
    if admissible and (available is None or not result.get('objective')):
        raise RuntimeError('admissible model attempt missing online availability: '+str(path))
    arrivals=([{'source':provider,'sequence':0,'tie_priority':1,
                'available_seconds':available,'objective':result['objective'],
                'metrics':result.get('metrics') or {}}] if admissible else [])
    return {'complete':True,'status':result.get('status','completed'),'arrivals':arrivals}


def self_test():
    def vector(value):return {k:(value if i==2 else 0.) for i,k in enumerate(TIERS)}
    arrivals=[{'source':'Full-MILP','available_seconds':1.,'objective':vector(10)},
              {'source':'luna','available_seconds':30.,'objective':vector(9)},
              {'source':'Full-MILP','available_seconds':40.,'objective':vector(8)}]
    deliveries,events=replay(arrivals)
    assert at(deliveries,30)['source']=='Full-MILP'
    assert at(deliveries,31)['source']=='luna'
    assert at(deliveries,60)['source']=='Full-MILP'
    assert all(e['selector_finish_seconds']>=e['source_available_seconds']+e['comparison_selection_seconds'] for e in events)
    assert all(e['comparison_selection_seconds']>0 for e in events)
    # A tolerance tie retains the already-delivered candidate, in arrival order.
    tied=[{'source':'Full-MILP','available_seconds':1.,'objective':vector(10)},
          {'source':'luna','available_seconds':2.,'objective':vector(10+5e-8)}]
    assert replay(tied)[0][-1]['source']=='Full-MILP'
    pending=retain_pending({'admissible':True,'service_target':True,'reference_quality':False},False)
    assert pending['admissible'] is None and pending['known_admissible']
    print('PASS: cutoff includes selection overhead; arrival-order updates; public tolerance tie; pending not failure')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--online',type=Path,default=ROOT/'online/new_generation')
    p.add_argument('--deterministic',type=Path,default=ROOT/'results/new_comparison/runs')
    p.add_argument('--references',type=Path,default=ROOT/'new_networks/references')
    p.add_argument('--tasks',type=Path,default=ROOT/'new_networks/tasks')
    p.add_argument('--output',type=Path,default=ROOT/'results/arrival_selection')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:
        self_test();return
    a.output.mkdir(parents=True,exist_ok=True)
    bindings=[b for b in read(a.online/'BINDINGS.json') if b['repeat']==1]
    records=sorted(set(b['record_id'] for b in bindings))
    binding_map={(b['record_id'],b['provider']):b for b in bindings}
    singles=[];pairs=[];selection_events=[];source_status=[]
    for rid in records:
        task=read(a.tasks/(rid+'.json'))
        urgent=sum(m['priority']=='urgent' for m in task['missions'])
        total=len(task['missions'])
        refpath=a.references/(rid+'.json')
        ref=read(refpath) if refpath.exists() else {}
        if 'reference' in ref:ref=ref['reference']
        context={'record_id':rid,'network_id':binding_map[rid,'deepseek']['network_id'],
                 'condition':binding_map[rid,'deepseek']['condition']}
        sources={method:load_deterministic(a.deterministic/f'{rid}__{method}.json',method) for method in DETERMINISTIC}
        for provider in PROVIDERS:
            binding=binding_map[rid,provider]
            sources[provider]=load_model(a.online/'attempts'/binding['attempt_id']/'TERMINAL.json',provider)
        for method,source in sources.items():
            source_status.append({**context,'method':method,'complete':source['complete'],
                                  'status':source['status'],'delivered_candidates':len(source['arrivals'])})
            for budget in BUDGETS:
                candidate=at(source['arrivals'],budget)
                row={**context,'method':method,'seconds':budget,'source_status':source['status'],
                     'scope':'independently measured source availability',
                     **candidate_fields(candidate,ref,urgent,total)}
                singles.append(retain_pending(row,source['complete']))
        for method in ('Full-MILP','Iter-R4'):
            for provider in PROVIDERS:
                deterministic,model=sources[method],sources[provider]
                delivered,events=replay(deterministic['arrivals']+model['arrivals'])
                complete=deterministic['complete'] and model['complete']
                pair=method+'+'+provider
                for event in events:
                    selection_events.append({**context,'pair':pair,'scope':SCOPE,**event})
                for budget in BUDGETS:
                    candidate=at(delivered,budget)
                    baseline=at(deterministic['arrivals'],budget)
                    cf=candidate_fields(candidate,ref,urgent,total)
                    bf=candidate_fields(baseline,ref,urgent,total)
                    strict=bool(candidate and (baseline is None or compare(candidate['objective'],baseline['objective'])<0))
                    row={**context,'method':pair,'deterministic':method,'provider':provider,'seconds':budget,
                         'deterministic_status':deterministic['status'],'model_status':model['status'],
                         'scope':SCOPE,**cf,
                         'model_selected':cf['selected_source']==provider,
                         'strict_quality_gain_over_deterministic':strict if complete else None,
                         'new_service_target_hit':cf['service_target'] and not bf['service_target'] if complete else None,
                         'new_reference_quality_hit':cf['reference_quality'] and not bf['reference_quality'] if complete else None,
                         'additional_urgent_served':cf['urgent_served']-bf['urgent_served'] if complete and cf['urgent_served'] is not None and bf['urgent_served'] is not None else None,
                         'additional_total_served':cf['total_served']-bf['total_served'] if complete and cf['total_served'] is not None and bf['total_served'] is not None else None,
                         'comparison_selection_seconds_through_cutoff':sum(e['comparison_selection_seconds'] for e in events if e['selector_finish_seconds']<=budget)}
                    pairs.append(retain_pending(row,complete))
    csvout(a.output/'single_method_budget_slices.csv',singles)
    csvout(a.output/'pair_budget_slices.csv',pairs)
    csvout(a.output/'selection_events.csv',selection_events)
    csvout(a.output/'source_status.csv',source_status)
    summary=[]
    for method in list(DETERMINISTIC)+list(PROVIDERS)+[d+'+'+m for d in ('Full-MILP','Iter-R4') for m in PROVIDERS]:
        dataset=pairs if '+' in method else singles
        for budget in BUDGETS:
            rows=[r for r in dataset if r['method']==method and r['seconds']==budget]
            complete=[r for r in rows if r['analysis_complete']]
            item={'method':method,'seconds':budget,'scheduled_tasks':len(rows),
                  'completed_tasks':len(complete),'pending_tasks':len(rows)-len(complete),
                  'admissible':sum(bool(r['admissible']) for r in complete),
                  'service_target':sum(bool(r['service_target']) for r in complete),
                  'reference_quality':sum(bool(r['reference_quality']) for r in complete),
                  'reference_certified_denominator':sum(r['reference_certified'] for r in complete),
                  'known_admissible_including_partial':sum(r['known_admissible'] for r in rows),
                  'known_reference_quality_including_partial':sum(r['known_reference_quality'] for r in rows)}
            if '+' in method:
                item.update(strict_quality_gain_tasks=sum(r['strict_quality_gain_over_deterministic'] for r in complete),
                            new_service_target_hits=sum(r['new_service_target_hit'] for r in complete),
                            new_reference_quality_hits=sum(r['new_reference_quality_hit'] for r in complete))
            summary.append(item)
    csvout(a.output/'budget_summary.csv',summary)
    report={'scope':SCOPE,'joint_execution_measured':False,'formal_model_repeat':1,
            'scheduled_tasks':len(records),'cutoffs_seconds':BUDGETS,
            'tie_rule':'deterministic first at exact equal arrival; comparator ties retain current selection',
            'arrival_stream':'deterministic published improving plans plus one verified model plan',
            'selector_overhead':'measured compare-and-select time per proposal, serial queue added to source availability',
            'pending_rule':'formal hit fields blank until required source runs complete; known delivered plans separately retained',
            'comparison_selection_seconds_total':sum(e['comparison_selection_seconds'] for e in selection_events),
            'source_status_counts':dict(Counter(r['status'] for r in source_status)),
            'summary':summary}
    (a.output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='summary'},indent=2))


if __name__=='__main__':main()
