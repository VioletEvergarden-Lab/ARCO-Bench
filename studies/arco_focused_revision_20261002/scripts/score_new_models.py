"""Offline scoring of all scheduled attempts, retaining pending and failures."""
from pathlib import Path
import argparse
import csv
import json
import statistics
import time
from collections import Counter,defaultdict
from run_new_models import ROOT,DEFAULT_ONLINE,read,rebuild_request,PROTOCOL
from optimization_online import Engine,compare,quality,TIERS,QUALITY_TOL,metrics
from optimization_summary import csvout


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--online',type=Path,default=DEFAULT_ONLINE)
    p.add_argument('--references',type=Path,default=ROOT/'new_networks/references')
    p.add_argument('--output',type=Path,default=ROOT/'results/generation')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    bindings=read(a.online/'BINDINGS.json')
    rows=[];scores=[];pairs=[]
    for b in bindings:
        file=a.online/'attempts'/b['attempt_id']/'TERMINAL.json'
        terminal=read(file) if file.exists() else {}
        refpath=a.references/(b['record_id']+'.json')
        ref=read(refpath) if refpath.exists() else {}
        if 'reference' in ref:ref=ref['reference']
        certified=bool(ref.get('optimal') or ref.get('global_optimal'))
        prefix=6 if certified else int(ref.get('proved_prefix',0))
        reference=ref.get('objective')
        score=None
        if terminal.get('decisions'):
            task,_=rebuild_request(b)
            score=Engine(task).verify(terminal['decisions'])
            if score['admissible']!=terminal.get('admissible') or score['objective']!=terminal.get('objective'):
                raise RuntimeError('online/offline score mismatch '+b['attempt_id'])
        admissible=bool(score and score['admissible'])
        vector=score['objective'] if admissible else None
        miss=next((k for k,t in zip(TIERS,QUALITY_TOL) if abs(vector[k]-reference[k])>t+1e-10),None) if admissible and certified else None
        row={k:b[k] for k in ('attempt_id','record_id','network_id','public_record_id','condition','provider','repeat','rank')}
        row.update(status=terminal.get('status','pending'),admissible=admissible,
                   reference_certified=certified,reference_service_certified=prefix>=2,
                   reference_quality=bool(admissible and certified and quality(vector,reference)),
                   service_target=bool(admissible and prefix>=2 and all(vector[k]==reference[k] for k in TIERS[:2])),
                   first_miss=miss,first_gap=vector[miss]-reference[miss] if miss else None,
                   objective=vector,response_seconds=terminal.get('response_seconds'),
                   available_seconds=terminal.get('available_seconds'),
                   validation_seconds=terminal.get('validation_seconds'),
                   preparation_seconds=terminal.get('preparation_seconds'),
                   returned_model=terminal.get('returned_model'),finish_reason=terminal.get('finish_reason'),
                   errors=terminal.get('errors'),usage=terminal.get('usage'))
        if admissible:row.update(metrics(task,score))
        rows.append(row)
        scores.append({**row,'decisions':terminal.get('decisions'),'score':score})
        if terminal:
            for method in ('Full-MILP','Iter-R4'):
                detpath=ROOT/'results/new_comparison/runs'/f"{b['record_id']}__{method}.json"
                if not detpath.exists():continue
                deterministic=read(detpath)
                select_start=time.perf_counter()
                dv=deterministic.get('objective')
                choose_model=admissible and (not dv or compare(vector,dv)<0)
                chosen=vector if choose_model else dv
                select_seconds=time.perf_counter()-select_start
                detquality=bool(dv and certified and quality(dv,reference))
                modelquality=row['reference_quality']
                pairs.append({'attempt_id':b['attempt_id'],'record_id':b['record_id'],
                    'network_id':b['network_id'],'provider':b['provider'],'repeat':b['repeat'],
                    'deterministic':method,'selected':b['provider'] if choose_model else method,
                    'admissible':chosen is not None,'reference_certified':certified,
                    'reference_quality':bool(chosen and certified and quality(chosen,reference)),
                    'model_only_reference_quality':modelquality and not detquality,
                    'deterministic_only_reference_quality':detquality and not modelquality,
                    'model_strictly_improves':choose_model,
                    'selection_seconds_offline':select_seconds,
                    'scope':'static selection from independently delivered plans',
                    'objective':chosen})
    csvout(a.output/'per_attempt.csv',rows)
    csvout(a.output/'main_per_task.csv',[r for r in rows if r['repeat']==1])
    csvout(a.output/'deterministic_pairing.csv',pairs)
    (a.output/'scores.json').write_text(json.dumps(scores,indent=2),encoding='utf-8')
    summary={'protocol':PROTOCOL,'scheduled':len(rows),'completed':sum(r['status']!='pending' for r in rows),'main':{},'all_attempts':{}}
    for scope in ('main','all_attempts'):
        for provider in ('deepseek','luna'):
            sub=[r for r in rows if r['provider']==provider and (scope=='all_attempts' or r['repeat']==1)]
            summary[scope][provider]={'scheduled':len(sub),'statuses':dict(Counter(r['status'] for r in sub)),
                'admissible':sum(r['admissible'] for r in sub),'service_target':sum(r['service_target'] for r in sub),
                'reference_quality':sum(r['reference_quality'] for r in sub),
                'certified_reference_denominator':sum(r['reference_certified'] for r in sub)}
            times=[r['available_seconds'] for r in sub if r['available_seconds'] is not None]
            summary[scope][provider]['available_time']={'hits':len(times),'denominator':len(sub),
                'median_among_hits':statistics.median(times) if times else None}
    summary['main_static_pairing']={}
    for method in ('Full-MILP','Iter-R4'):
        for provider in ('deepseek','luna'):
            sub=[r for r in pairs if r['repeat']==1 and r['provider']==provider and r['deterministic']==method]
            summary['main_static_pairing'][method+'+'+provider]={
                'completed_model_attempts':len(sub),'reference_quality':sum(r['reference_quality'] for r in sub),
                'model_only_reference_quality':sum(r['model_only_reference_quality'] for r in sub),
                'model_strictly_improves':sum(r['model_strictly_improves'] for r in sub)}
    repeated=[]
    by=defaultdict(list)
    for r in rows:by[r['record_id'],r['provider']].append(r)
    for (rid,provider),sub in by.items():
        if len(sub)==3:
            repeated.append({'record_id':rid,'network_id':sub[0]['network_id'],'provider':provider,
                'scheduled':3,'completed':sum(r['status']!='pending' for r in sub),
                'admissible_count':sum(r['admissible'] for r in sub),
                'service_count':sum(r['service_target'] for r in sub),
                'reference_quality_count':sum(r['reference_quality'] for r in sub),
                'reference_certified':sub[0]['reference_certified'],
                'attempt_ids':[r['attempt_id'] for r in sub]})
    csvout(a.output/'repetition_by_base.csv',repeated)
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
