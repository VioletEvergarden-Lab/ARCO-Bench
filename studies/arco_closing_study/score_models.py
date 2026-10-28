"""Offline replay with separate network, same-batch anchor and archived Core scopes."""
import argparse
import json
from collections import Counter,defaultdict
from study_common import HERE,P,R25,Runtime,read,write,jl,jsonl,csvout,TIERS
from continuous_engine import Engine,parse,quality,compare,QUALITY_TOL
from common import quality as core_quality

def miss_layer(vector,ref,tols):
    return next((name for name,tol in zip(TIERS,tols) if abs(vector[name]-ref[name])>tol+1e-10),None)

def model_score(task,terminal,engine=None,runtime=None):
    if not terminal: return {'status':'pending','admissible':False,'decisions':None,'objective':None,'errors':[]}
    if not terminal.get('usable_text'): return {'status':'no_answer','admissible':False,'decisions':None,'objective':None,'errors':[terminal.get('finish_reason')]}
    raw=terminal['raw_text']
    if engine:
        ds,errors=parse(raw,task)
        if errors: return {'status':'schema_invalid','admissible':False,'decisions':None,'objective':None,'errors':errors}
        score=engine.verify(ds); admissible=score['admissible']; vector=score['objective']; errors=score['errors']
        if any(e.startswith('SCHEMA_') for e in errors): return {'status':'schema_invalid','admissible':False,'decisions':ds,'objective':None,'errors':errors,'score':score}
    else:
        parsed,errors=runtime.selector.parse_public(raw,task)
        if errors: return {'status':'schema_invalid','admissible':False,'decisions':None,'objective':None,'errors':errors}
        score=runtime.selector.public_evaluate(parsed,errors,task,runtime.formal); ds=parsed['decisions'] if isinstance(parsed,dict) else parsed; admissible=score['formal_feasible']; vector=score['objective_vector']; errors=score.get('formal_error_codes',[])
    return {'status':'admissible' if admissible else 'infeasible','admissible':admissible,'decisions':ds,'objective':vector,'errors':errors,'score':score}

def main(partial=False):
    root=HERE/'online'; bindings=read(root/'BINDINGS.json'); runtime=Runtime(); rows=[]; scored=[]; pairs=[]; events=[]; refs_core={r['record_id']:r['objective'] for r in jl(P/'references/public_domain.jsonl')}; r4_core={r['record_id']:r for r in read(HERE/'core_r4/results.json')}; greedy_core={r['record_id']:json.loads(r['raw_text'])['decisions'] for r in jl(R25/'policy_domains/public_both.jsonl')}
    task_ids=list(dict.fromkeys(b['record_id'] for b in bindings)); lookup={(b['provider'],b['record_id']):b for b in bindings}
    for rid in task_ids:
        layer=lookup['deepseek',rid]['layer']; isnet=layer=='network'; task=read((HERE/'networks/tasks' if isnet else P/'data/public/records')/f'{rid}.json'); engine=Engine(task) if isnet else None
        if isnet:
            task['record_id']=lookup['deepseek',rid]['public_record_id']; engine=Engine(task)
        ref=read(HERE/'networks/references'/f'{rid}.json')['objective'] if isnet else refs_core[rid]; check=quality if isnet else core_quality
        reference_decisions=read(HERE/'networks/references'/f'{rid}.json')['decisions'] if isnet else None
        tols=QUALITY_TOL if isnet else (0,0,0,0,0,1e-4)
        if isnet:
            candidate=read(HERE/'networks/candidates'/f'{rid}.json'); dets={s:{'decisions':candidate[s]['decisions'] if s=='G' else candidate[s]['result']['decisions'],'score':candidate[s]['score'],'admissible':bool(candidate[s]['score'] and candidate[s]['score']['admissible']),'objective':candidate[s]['score']['objective'] if candidate[s]['score'] else None} for s in ['G','R4']}
        else:
            dets={}
            for source,ds in [('G',greedy_core[rid]),('R4',r4_core[rid]['decisions'])]:
                score=runtime.evaluate(task,ds); dets[source]={'decisions':ds,'score':score,'admissible':score['formal_feasible'],'objective':score['objective_vector']}
        model_results={}
        for provider in ['deepseek','luna']:
            path=root/provider/'attempts'/rid/'TERMINAL.json'; terminal=read(path) if path.exists() else None
            if not partial and terminal is None: raise RuntimeError(('missing attempt',provider,rid))
            model_results[provider]=model_score(task,terminal,engine,runtime)
        sources={**dets,**model_results}
        for source,result in sources.items():
            admissible=result['admissible']; vector=result['objective']; achieved=bool(admissible and check(vector,ref)); status='reference_quality' if achieved else 'admissible_miss' if admissible else result.get('status','infeasible')
            result.update(quality=achieved,status=status)
            missions=task['missions'] if isnet else task['instance']['missions']; mission_count=len(missions); urgent_count=sum(m['priority']=='urgent' for m in missions)
            extra={}
            if admissible:
                extra={'urgent_hold_difference':vector['urgent_holds']-ref['urgent_holds'],'total_hold_difference':vector['total_holds']-ref['total_holds'],'additional_urgent_fraction':(vector['urgent_holds']-ref['urgent_holds'])/urgent_count if urgent_count else None,'hold_difference_fraction':(vector['total_holds']-ref['total_holds'])/mission_count}
                if isnet:
                    served=sorted(d['mission_id'] for d in result['decisions'] if not d['held']); reference_served=sorted(d['mission_id'] for d in reference_decisions if not d['held'])
                    extra.update(served_missions=served,same_service_as_reference=served==reference_served,energy_difference_same_service_kwh=vector['energy_kwh']-ref['energy_kwh'] if served==reference_served else None,reference_prefix_through_L5=all(abs(vector[tier]-ref[tier])<=tol+1e-10 for tier,tol in list(zip(TIERS,tols))[:5]))
            row={'record_id':rid,'layer':layer,'network_id':rid[:-2] if isnet else None,'scale':rid.split('_')[1][0] if isnet else 'Core','condition':rid[-1] if isnet else 'anchor','source':source,'status':status,'admissible':admissible,'reference_quality':achieved,'first_miss':miss_layer(vector,ref,tols) if admissible and not achieved else None,'mission_count':mission_count,'urgent_count':urgent_count,'reference':ref,'objective':vector,'errors':result.get('errors',[]),**extra}
            if source in model_results and (root/source/'attempts'/rid/'TERMINAL.json').exists():
                terminal=read(root/source/'attempts'/rid/'TERMINAL.json'); row.update({k:terminal.get(k) for k in ['requested_model','returned_model','post_start_utc','terminal_utc','latency_seconds','usage','finish_reason']})
            rows.append(row); scored.append({'record_id':rid,'layer':layer,'source':source,**result})
            if isnet and result.get('score'): events.extend(dict(e,record_id=rid,source=source) for e in result['score'].get('events',[]))
        for deterministic in ['G','R4']:
            for provider in model_results:
                d=sources[deterministic]; m=sources[provider]
                if m['status']=='pending': continue
                d_selected=d['admissible'] and (not m['admissible'] or (compare(d['objective'],m['objective']) if isnet else runtime.selector.lex_compare(d['objective'],m['objective']))<=0)
                chosen=deterministic if d_selected else provider; selected=sources[chosen]
                pairs.append({'record_id':rid,'layer':layer,'network_id':rid[:-2] if isnet else None,'scale':rid.split('_')[1][0] if isnet else 'Core','condition':rid[-1] if isnet else 'anchor','pair':deterministic+'+'+provider,'selected':chosen,'admissible':selected['admissible'],'reference_quality':selected['quality'],'D_quality':d['quality'],'model_quality':m['quality'],'model_only':m['quality'] and not d['quality'],'D_only':d['quality'] and not m['quality'],'objective':selected['objective']})
    summary={}
    for layer in ['network','core_anchor']:
        summary[layer]={'sources':{},'pairs':{}}
        for source in ['G','R4','deepseek','luna']:
            subset=[r for r in rows if r['layer']==layer and r['source']==source]; count=Counter(r['status'] for r in subset)
            summary[layer]['sources'][source]={'tasks':len(subset),'admissible':sum(r['admissible'] for r in subset),'reference_quality':sum(r['reference_quality'] for r in subset),'statuses':dict(count),'first_miss':dict(Counter(r['first_miss'] for r in subset if r['first_miss'])),'extra_urgent_holds':sum(r.get('urgent_hold_difference',0) for r in subset),'total_hold_difference':sum(r.get('total_hold_difference',0) for r in subset)}
        for pair in sorted(set(r['pair'] for r in pairs)):
            subset=[r for r in pairs if r['layer']==layer and r['pair']==pair]; summary[layer]['pairs'][pair]={'tasks':len(subset),'admissible':sum(r['admissible'] for r in subset),'reference_quality':sum(r['reference_quality'] for r in subset),'selected_sources':dict(Counter(r['selected'] for r in subset)),'model_only':sum(r['model_only'] for r in subset),'D_only':sum(r['D_only'] for r in subset)}
    out=HERE/'evaluation'; write(out/'summary.json',summary); write(out/'scores.json',scored); csvout(out/'per_task.csv',rows); csvout(out/'selection.csv',pairs); write(out/'selection.json',pairs); csvout(out/'events.csv',events)
    # Reuse the same visible model answers with only resource width changed.
    sensitivity=[]
    for rid in read(HERE/'window_sensitivity/config.json')['task_ids']:
        if partial and not (HERE/'window_sensitivity/results'/f'{rid}.json').exists(): continue
        record=read(HERE/'window_sensitivity/results'/f'{rid}.json'); task=read(HERE/'window_sensitivity/tasks'/f'{rid}.json'); task['record_id']=lookup['deepseek',rid]['public_record_id']; eng=Engine(task)
        for provider in ['deepseek','luna']:
            path=root/provider/'attempts'/rid/'TERMINAL.json'; terminal=read(path) if path.exists() else None; result=model_score(task,terminal,eng,runtime); result['quality']=bool(result['admissible'] and record['reference']['optimal'] and quality(result['objective'],record['reference']['objective'])); sensitivity.append({'record_id':rid,'provider':provider,**result})
    write(out/'window_model_replay.json',sensitivity); print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--partial',action='store_true'); a=p.parse_args(); main(a.partial)
