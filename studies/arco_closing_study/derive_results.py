"""Small, source-backed summaries for the paper (no online generation)."""
from collections import Counter
import numpy as np
from study_common import HERE,read,write,csvout,TIERS
from continuous_engine import Engine,flight,quality,QUALITY_TOL,buckets

LABELS={'G':'Greedy $G$','R4':'Local repair $R_4$','deepseek':'DeepSeek V4-Pro','luna':'GPT-5.6 Luna',
        'G+deepseek':'$G$ + DeepSeek','G+luna':'$G$ + Luna','R4+deepseek':'$R_4$ + DeepSeek','R4+luna':'$R_4$ + Luna'}

def distribution(xs):
    x=np.asarray(xs,dtype=float)
    return dict(n=len(x),minimum=float(x.min()),median=float(np.median(x)),p95=float(np.quantile(x,.95)),maximum=float(x.max())) if len(x) else None

def base():
    paths=[]; events=[]; networks=[]; refs=[];reservations=[]
    for p in sorted((HERE/'networks/tasks').glob('NET_*.json')):
        t=read(p); e=Engine(t); r=read(HERE/'networks/references'/p.name)
        assert r['optimal'] and r['proved_prefix']==6
        s=e.verify(r['decisions']); assert s['admissible']
        refs.append(dict(record_id=p.stem,scale=p.stem.split('_')[1][0],condition=p.stem[-1],**r['objective'],seconds=r['total_seconds']))
        events.extend(dict(ev,source='reference') for ev in s['events'])
        reservations.extend(dict(record_id=p.stem,kind=x['kind'],resource=x['resource'],actual_min=x['end_min']-x['start_min'],reserved_min=len(buckets(x['start_min'],x['end_min'],e.width))*e.width) for x in s['resource_intervals'])
        if p.stem[-1]=='A':
            chains=Counter(m['uav_id'] for m in t['missions'])
            networks.append(dict(network_id=p.stem[:-2],scale=p.stem.split('_')[1][0],uavs=len(t['fleet']),missions=len(t['missions']),nodes=len(t['nodes']),corridors=len(t['corridors']),min_chain=min(chains.values()),max_chain=max(chains.values()),incoming=sum(bool(m.get('incoming')) for m in t['missions']),successors=len(t['missions'])-len(t['fleet']),chargers=sum(v>0 for v in t['resources']['charger'].values()),horizon_min=t['timing']['horizon_departure_min']))
            for m in t['missions']:
                for path in m['paths']:
                    f=flight(t,path,m['payload_kg']); paths.append(dict(network_id=p.stem[:-2],mission_id=m['mission_id'],path_id=path['path_id'],segments=len(path['corridor_ids']),**{k:f[k] for k in ('distance_km','flight_min','energy_kwh')}))
    actual=[ev for ev in events if not ev['held']]
    stats={'networks':len(networks),'tasks':len(refs),'mission_occurrences':sum(n['missions']*3 for n in networks),'base_missions':sum(n['missions'] for n in networks),
           'incoming_successors':sum(n['incoming'] for n in networks),'successors':sum(n['successors'] for n in networks),
           'candidate_paths':{k:distribution([r[k] for r in paths]) for k in ('distance_km','flight_min','energy_kwh','segments')},
           'reference_events':{k:distribution([r[k] for r in actual]) for k in ('continuous_flight_min','reserve_margin_kwh','flight_energy_kwh','charge_blocks')},
           'reference_charge_minutes':distribution([r['charge_blocks']*5 for r in actual]),
           'reference_actions':dict(route_changes=sum(r['route_changed'] for r in actual),departure_changes=sum(r['departure_shift_min']>0 for r in actual),charging_missions=sum(r['charge_blocks']>0 for r in actual)),
           'reservation_lengths':{kind:{k:distribution([r[k] for r in reservations if r['kind']==kind]) for k in ('actual_min','reserved_min')} for kind in ('corridor','charger')},
           'reference_optimization_seconds':distribution([r['seconds'] for r in refs]),
           'C_service':[{k:r[k] for k in ('record_id','urgent_holds','total_holds')} for r in refs if r['condition']=='C']}
    out=HERE/'derived';write(out/'physical_and_structure.json',stats);csvout(out/'networks.csv',networks);csvout(out/'available_paths.csv',paths);csvout(out/'reference_events.csv',events);csvout(out/'reference_reservations.csv',reservations);csvout(out/'references.csv',refs)
    return stats,networks

def final(available=False):
    bindings=read(HERE/'online/BINDINGS.json');pending=[b for b in bindings if not (HERE/'online'/b['provider']/'attempts'/b['record_id']/'TERMINAL.json').exists()]
    if not available:assert not pending,('formal attempts pending',len(pending))
    stats,networks=base(); rows=[]
    for p in sorted((HERE/'networks/candidates').glob('NET_*.json')):
        c=read(p);r=read(HERE/'networks/references'/p.name)
        for src in ('G','R4'):
            v=c[src]['score']['objective'];rows.append(dict(record_id=p.stem,source=src,quality=c[src]['quality'],seconds=c[src]['total_seconds'] if src=='G' else c[src]['full_seconds'],proved_prefix=c[src]['result']['proved_prefix'] if src=='R4' else None,**v))
    assert len(rows)==72
    evals=read(HERE/'evaluation/scores.json'); selections=read(HERE/'evaluation/selection.json')
    # The serialized CSV is only an interchange product; use typed JSON here.
    per=[]
    for r in evals:
        if r['layer']!='network': continue
        rid=r['record_id']; t=read(HERE/'networks/tasks'/f'{rid}.json'); ref=read(HERE/'networks/references'/f'{rid}.json');v=r['objective'];n=len(t['missions']);nu=sum(m['priority']=='urgent' for m in t['missions'])
        served={d['mission_id'] for d in r['decisions'] if not d['held']} if r.get('decisions') else set()
        rs={d['mission_id'] for d in ref['decisions'] if not d['held']}
        per.append(dict(record_id=rid,network_id=rid[:-2],scale=rid.split('_')[1][0],condition=rid[-1],source=r['source'],admissible=r['admissible'],quality=r['quality'],status=r['status'],mission_count=n,urgent_count=nu,extra_urgent_holds=v['urgent_holds']-ref['objective']['urgent_holds'] if r['admissible'] else None,extra_total_holds=v['total_holds']-ref['objective']['total_holds'] if r['admissible'] else None,extra_total_fraction=(v['total_holds']-ref['objective']['total_holds'])/n if r['admissible'] else None,same_service_set=r['admissible'] and served==rs,energy_difference_same_service_kwh=v['energy_kwh']-ref['objective']['energy_kwh'] if r['admissible'] and served==rs else None,first_miss=next((k for k,tol in zip(TIERS,QUALITY_TOL) if abs(v[k]-ref['objective'][k])>tol+1e-10),None) if r['admissible'] and not r['quality'] else None))
    allrows=per+[dict(record_id=s['record_id'],network_id=s['network_id'],scale=s['scale'],condition=s['condition'],source=s['pair'],admissible=s['admissible'],quality=s['reference_quality']) for s in selections if s['layer']=='network']
    summary={};conditions=[];heat=[]
    for src in LABELS:
        ss=[r for r in allrows if r['source']==src]
        summary[src]=dict(admissible=sum(r['admissible'] for r in ss),quality=sum(r['quality'] for r in ss),tasks=len(ss))
        for c in 'ABC':
            cc=[r for r in ss if r['condition']==c];conditions.append(dict(source=src,condition=c,tasks=len(cc),admissible=sum(r['admissible'] for r in cc),quality=sum(r['quality'] for r in cc)))
        for scale in 'SML':
            for c in 'ABC':
                cc=[r for r in ss if r['condition']==c and r['scale']==scale];heat.append(dict(source=src,scale=scale,condition=c,tasks=len(cc),quality=sum(r['quality'] for r in cc)))
        if '+' not in src:
            aa=[r for r in ss if r['admissible']]
            summary[src].update(statuses=dict(Counter(r['status'] for r in ss)),first_miss=dict(Counter(r['first_miss'] for r in aa if r['first_miss'])),extra_urgent_holds=sum(r['extra_urgent_holds'] for r in aa),extra_total_holds=sum(r['extra_total_holds'] for r in aa),admissible_service_denominator=len(aa),mean_extra_total_fraction=float(np.mean([r['extra_total_fraction'] for r in aa])) if aa else None,same_service_energy_denominator=sum(r['same_service_set'] for r in aa),energy_difference_same_service=distribution([r['energy_difference_same_service_kwh'] for r in aa if r['same_service_set']]))
    latency={}
    for src in ('deepseek','luna'):
        ts=[read(p) for p in (HERE/'online'/src/'attempts').glob('*/TERMINAL.json')]
        latency[src]=dict(seconds=distribution([r['latency_seconds'] for r in ts]),usable_response_seconds=distribution([r['latency_seconds'] for r in ts if r['usable_text']]),returned_models=dict(Counter(r['returned_model'] for r in ts if r.get('returned_model'))),first_request=min(r['post_start_utc'] for r in ts),last_terminal=max(r['terminal_utc'] for r in ts))
    timing={src:distribution([r['seconds'] for r in rows if r['source']==src]) for src in ('G','R4')}
    timing['R4_complete']=sum(r['proved_prefix']==6 for r in rows if r['source']=='R4')
    windows=[]
    for rid in read(HERE/'window_sensitivity/config.json')['task_ids']:
        fine=read(HERE/'window_sensitivity/results'/f'{rid}.json');coarse=read(HERE/'networks/references'/f'{rid}.json');fv=fine['reference']['objective'];cv=coarse['objective']
        windows.append(dict(record_id=rid,half_minute_reference_optimal=fine['reference']['optimal'],half_minute_proved_prefix=fine['reference']['proved_prefix'],reference_equal=quality(fv,cv) if fv else False,one_minute=cv,half_minute=fv))
    out=HERE/'derived';write(out/'paper_summary.json',dict(completion=dict(planned=96,terminal=96-len(pending),pending=pending),sources=summary,timing=timing,latency=latency,window_comparison=windows));write(out/'source_per_task.json',per);csvout(out/'source_per_task.csv',per);csvout(out/'quality_by_scale_condition.csv',heat);csvout(out/'quality_by_condition.csv',conditions);csvout(out/'deterministic_times.csv',rows)
    return summary

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--base',action='store_true');p.add_argument('--available',action='store_true');a=p.parse_args()
    print(base()[0] if a.base else final(a.available))
