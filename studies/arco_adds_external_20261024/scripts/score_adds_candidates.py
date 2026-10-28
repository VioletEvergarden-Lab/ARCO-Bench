"""Replay original ADDS submissions and score only against certified references.

Read-only on requests/terminals/reference files; writes derived evaluation files.
No generation or optimization is invoked.
"""
from pathlib import Path
from collections import Counter
import argparse,csv,hashlib,json
import run_adds_candidates as runner
ROOT=runner.ROOT

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def csvout(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,keys);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
def same_vector(a,b,tol=1e-10):
    return a is None and b is None or a is not None and b is not None and set(a)==set(b) and all(abs(a[k]-b[k])<=tol for k in a)

def main(online,reference_dir,output):
    ce=runner.runtime();config=runner.read(online/'CONFIG.json');bindings=runner.effective_bindings(online,runner.read(online/'BINDINGS.json'),offline=True)
    if len({b['attempt_id'] for b in bindings})!=len(bindings):raise RuntimeError('duplicate attempt IDs')
    if any(b['repeat']!=1 for b in bindings):raise RuntimeError('ADDS main group uses first requests only')
    rows=[];details=[];source_hashes={};reference_checks={}
    for b in bindings:
        task,_=runner.rebuild(b,config);engine=ce.Engine(task)
        folder=online/'attempts'/b['attempt_id'];tp=folder/'TERMINAL.json';intent=folder/'SUBMISSION_INTENT.json';post=folder/'POST_HTTP.json'
        terminal=runner.read(tp) if tp.exists() else {}
        if tp.exists():source_hashes[tp.relative_to(ROOT).as_posix()]=runner.sha(tp.read_bytes())
        pm=runner.read(post) if post.exists() else {}
        submission=terminal.get('submission_state')
        if not submission:
            submission=('not_submitted' if not intent.exists() else 'accepted' if (folder/'RESPONSE_ID.json').exists() or pm.get('http_status')==200
                else 'uncertain_delivery' if not post.exists() or pm.get('http_status') is None or pm.get('http_status',0)>=500 else 'rejected')
        status=terminal.get('status','accepted_pending' if submission=='accepted' else 'not_submitted' if submission=='not_submitted' else 'request_unresolved')
        decisions=score=None;schema_complete=False;raw_path=folder/'PROVIDER_RAW.json'
        if terminal.get('usable_text'):
            if not raw_path.exists():raise RuntimeError('original usable response missing: '+b['attempt_id'])
            raw=raw_path.read_bytes();meta=runner.read(folder/'PROVIDER_HTTP.json')
            obj,text,state,identity,ok,usable=runner.extract(b['provider'],meta,raw)
            if not usable or text!=terminal.get('raw_text') or runner.sha(raw)!=terminal.get('raw_response_sha256'):
                raise RuntimeError('original provider response differs: '+b['attempt_id'])
            decisions,errors=ce.parse(text,task)
            if errors:status='schema_invalid'
            else:
                score=engine.verify(decisions)
                schema_complete=not any(e.startswith('SCHEMA_') for e in score['errors'])
                status='admissible' if score['admissible'] else 'infeasible' if schema_complete else 'schema_invalid'
            if decisions!=terminal.get('decisions') or bool(score and score['admissible'])!=terminal.get('admissible'):
                raise RuntimeError('online/offline decisions or admissibility differ: '+b['attempt_id'])
            if not same_vector(score['objective'] if score else None,terminal.get('objective')):
                raise RuntimeError('online/offline objective differs: '+b['attempt_id'])
            source_hashes[raw_path.relative_to(ROOT).as_posix()]=runner.sha(raw)
        # Preserve complete physical-infeasible outputs for subsequent scope diagnosis.
        admissible=bool(score and score['admissible']);vector=score['objective'] if admissible else None
        refpath=reference_dir/(b['record_id']+'__Full-MILP.json')
        ref=runner.read(refpath) if refpath.exists() else {}
        certified=bool(ref.get('global_optimal') or ref.get('optimal'))
        prefix=6 if certified else max([int(n.get('proved_prefix',0)) for n in ref.get('neighborhoods',[])]+[int(ref.get('proved_prefix',0))])
        refvector=ref.get('objective');refvalid=False
        if ref:
            source_hashes[refpath.relative_to(ROOT).as_posix()]=runner.sha(refpath.read_bytes())
            if b['record_id'] not in reference_checks:
                rs=engine.verify(ref['decisions']) if ref.get('decisions') else None
                if not rs or not rs['admissible'] or not same_vector(rs['objective'],refvector):raise RuntimeError('reference replay mismatch: '+b['record_id'])
                if ref.get('task_sha256') and ref['task_sha256']!=b['task_sha256']:raise RuntimeError('reference task differs')
                reference_checks[b['record_id']]=dict(admissible=True,global_optimal=certified,proved_prefix=prefix,objective=rs['objective'])
            refvalid=reference_checks[b['record_id']]['admissible']
        quality=bool(admissible and refvalid and certified and ce.quality(vector,refvector)) if certified else None
        service=bool(admissible and refvalid and prefix>=2 and all(abs(vector[k]-refvector[k])<=tol+1e-10 for k,tol in zip(ce.TIERS[:2],ce.QUALITY_TOL[:2]))) if prefix>=2 else None
        miss=next((k for k,tol in zip(ce.TIERS,ce.QUALITY_TOL) if abs(vector[k]-refvector[k])>tol+1e-10),None) if admissible and certified else None
        if admissible and certified and ce.compare(vector,refvector)<0:raise RuntimeError('candidate improves a claimed optimum: '+b['attempt_id'])
        row={k:b.get(k) for k in ('rank','attempt_id','record_id','public_record_id','base_id','condition','provider','repeat')}
        row.update(status=status,submission_state=submission,submission_intent=intent.exists(),post_result_saved=post.exists(),
          terminal_record_saved=tp.exists(),provider_terminal_state=terminal.get('finish_reason'),
          requested_model=runner.MODELS[b['provider']],returned_model=terminal.get('returned_model'),
          http_status=terminal.get('http_status'),usable_text=bool(terminal.get('usable_text')),complete_decisions=schema_complete,admissible=admissible,
          reference_certified=certified,reference_proved_prefix=prefix,reference_quality=quality,service_target=service,
          scope_diagnosis_eligible=bool(schema_complete and certified and not quality),
          first_miss=miss,objective=vector,reference_objective=refvector,errors=score['errors'] if score else terminal.get('errors',[]),
          response_seconds=terminal.get('response_seconds'),available_seconds=terminal.get('available_seconds'),
          online_start_utc=terminal.get('online_start_utc'),terminal_utc=terminal.get('terminal_utc'),
          resumed_after_process_interruption=terminal.get('resumed_after_process_interruption'),usage=terminal.get('usage'))
        available=terminal.get('available_seconds')
        response=terminal.get('response_seconds')
        within=bool(admissible and available is not None and available<=600.)
        row.update(logical_attempt_id=b.get('logical_attempt_id',b['attempt_id']),
            response_within_600s=bool(tp.exists() and response is not None and response<=600.),
            admissible_within_600s=within,service_target_within_600s=bool(within and service),
            reference_quality_within_600s=bool(within and quality))
        if admissible:
            active=[e for e in score['events'] if not e['held']]
            row.update(mission_count=len(task['missions']),total_served=len(active),total_on_time=sum(e['tardiness_min']<=1e-7 for e in active),
                min_return_reserve_margin_kwh=min((e['reserve_margin_kwh'] for e in active),default=None))
        rows.append(row)
        details.append({**row,'decisions':decisions,'verification':score,'terminal_path':tp.relative_to(ROOT).as_posix() if tp.exists() else None,
            'original_raw_path':raw_path.relative_to(ROOT).as_posix() if raw_path.exists() else None})
    summary=dict(protocol=runner.PROTOCOL,formal_conditions=len({b['record_id'] for b in bindings}),planned_first_requests=len(bindings),
        generation_or_solver_calls_during_scoring=0,providers={},reference_checks=reference_checks,
        scoring='Original completed provider text parsed and independently replayed; no replacement by optimized witness',
        source_hashes=source_hashes)
    for provider in ('deepseek','luna'):
        subset=[r for r in rows if r['provider']==provider]
        summary['providers'][provider]=dict(planned_first_requests=len(subset),submission_intents=sum(r['submission_intent'] for r in subset),
            saved_post_results=sum(r['post_result_saved'] for r in subset),accepted=sum(r['submission_state']=='accepted' for r in subset),
            terminal_records=sum(r['terminal_record_saved'] for r in subset),complete_decisions=sum(r['complete_decisions'] for r in subset),
            admissible=sum(r['admissible'] for r in subset),service_target=sum(r['service_target'] is True for r in subset),
            reference_quality=sum(r['reference_quality'] is True for r in subset),certified_reference_denominator=sum(r['reference_certified'] for r in subset),
            timed_budget_seconds=600,response_within_600s=sum(r['response_within_600s'] for r in subset),
            admissible_within_600s=sum(r['admissible_within_600s'] for r in subset),
            service_target_within_600s=sum(r['service_target_within_600s'] for r in subset),
            reference_quality_within_600s=sum(r['reference_quality_within_600s'] for r in subset),
            diagnosis_eligible=sum(r['scope_diagnosis_eligible'] for r in subset),statuses=dict(Counter(r['status'] for r in subset)),
            submission_states=dict(Counter(r['submission_state'] for r in subset)))
    output.mkdir(parents=True,exist_ok=True)
    write(output/'scores.json',details);write(output/'summary.json',summary);csvout(output/'per_attempt.csv',rows)
    write(output/'diagnosis_inputs.json',[{'record_id':r['record_id'],'provider':r['provider'],'attempt_id':r['attempt_id'],
        'admissible':r['admissible'],'objective':r['objective'],'decisions':r['decisions'],'first_miss':r['first_miss']} for r in details if r['scope_diagnosis_eligible']])
    compact=dict(formal_conditions=summary['formal_conditions'],planned_first_generation_requests=len(bindings),
        evaluation_complete=all(r['terminal_record_saved'] for r in rows),
        terminal_records=sum(r['terminal_record_saved'] for r in rows),
        experimental_unit='one first actual generation request per frozen condition and provider',
        timed_budget_seconds=600,providers={})
    for provider in ('deepseek','luna'):
        s=[r for r in rows if r['provider']==provider]
        starts=[r['online_start_utc'] for r in s if r['online_start_utc']]
        ends=[r['terminal_utc'] for r in s if r['terminal_utc']]
        compact['providers'][provider]=dict(planned=len(s),submitted=sum(r['submission_intent'] for r in s),
            completed=sum(r['terminal_record_saved'] for r in s),schema_complete=sum(r['complete_decisions'] for r in s),
            admissible=sum(r['admissible'] for r in s),quality=sum(r['reference_quality'] is True for r in s),
            service_target=sum(r['service_target'] is True for r in s),
            no_output=sum(r['terminal_record_saved'] and not r['usable_text'] for r in s),
            schema_invalid=sum(r['status']=='schema_invalid' for r in s),
            infeasible=sum(r['complete_decisions'] and not r['admissible'] for r in s),
            admissible_gap=sum(r['admissible'] and r['reference_quality'] is False for r in s),
            complete_miss_diagnosis_denominator=sum(r['scope_diagnosis_eligible'] for r in s),
            admissible_within_600s=sum(r['admissible_within_600s'] for r in s),
            service_target_within_600s=sum(r['service_target_within_600s'] for r in s),
            quality_within_600s=sum(r['reference_quality_within_600s'] for r in s),
            first_request_start_utc=min(starts) if starts else None,last_terminal_utc=max(ends) if ends else None,
            status_counts=dict(Counter(r['status'] for r in s)))
    write(ROOT/'analysis/candidate_summary.json',compact)
    print(json.dumps({k:summary[k] for k in ('formal_conditions','planned_first_requests','providers')},indent=2))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--online',type=Path,default=ROOT/'runs/generation')
    p.add_argument('--references',type=Path,default=ROOT/'runs/deterministic');p.add_argument('--output',type=Path,default=ROOT/'analysis/candidate_evaluation')
    a=p.parse_args();main(a.online.resolve(),a.references.resolve(),a.output.resolve())
