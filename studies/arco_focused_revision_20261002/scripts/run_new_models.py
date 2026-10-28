"""Frozen 96-attempt evaluation; append-only attempts, online verification.

--prepare performs local validation only. --execute is the explicit POST gate.
The existing official HTTPS transport and confirmed historical model parameters
are reused. Repeated generations have distinct predeclared attempt IDs.
"""
from pathlib import Path
import argparse
import concurrent.futures
import copy
import datetime as dt
import hashlib
import json
import msvcrt
import os
import sys
import threading
import time

_library_start=time.perf_counter()
ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent/'arco_closing_study'
sys.dont_write_bytecode = True
sys.path.insert(0, str(OLD))
from continuous_engine import Engine, parse, compare
from provider_transport import MODELS, credentials, request, utc
from run_models import SETTINGS, SYSTEM, TERMINAL_STATES, canonical, sha, once, jo, prepared, decode, save_http
from optimization_online import metrics
LIBRARY_INITIALIZATION_SECONDS=time.perf_counter()-_library_start

PREPARED = ROOT/'new_networks/generation_prepared'
DEFAULT_ONLINE = ROOT/'online/new_generation'
PROTOCOL = 'new_generation_v1_20261003'
PRINT_LOCK = threading.Lock()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def say(*args):
    with PRINT_LOCK:
        print(*args, flush=True)


def rebuild_request(binding):
    """Executed within each attempt timer; references are never read here."""
    task = read(ROOT/'new_networks/tasks'/f"{binding['record_id']}.json")
    task['record_id'] = binding['public_record_id']
    task['model'].pop('slot_min', None)
    instruction = (OLD/'continuous_public_instructions.md').read_text(encoding='utf-8')
    user = instruction+'\n\nPublic task:\n\n'+canonical(task).decode('utf-8')
    if sha(user.encode('utf-8')) != binding['public_payload_sha256']:
        raise RuntimeError('frozen public payload differs')
    body = copy.deepcopy(SETTINGS[binding['provider']])
    key = 'messages' if binding['provider']=='deepseek' else 'input'
    body[key] = ([{'role':'system','content':SYSTEM}] if binding['provider']=='deepseek' else []) + [{'role':'user','content':user}]
    stored = (ROOT/binding['request_path']).read_bytes()
    if sha(stored) != binding['request_sha256'] or canonical(decode(stored)) != canonical(body):
        raise RuntimeError('frozen request differs')
    return task, stored


def prepare(root=DEFAULT_ONLINE):
    bindings = read(PREPARED/'BINDINGS.json')
    if len(bindings)>96 or len({b['attempt_id'] for b in bindings})!=len(bindings):
        raise RuntimeError('planned attempt limit or ID uniqueness')
    if sorted(b['rank'] for b in bindings)!=list(range(1,len(bindings)+1)):
        raise RuntimeError('frozen rank sequence')
    for b in bindings:
        rebuild_request(b)
    config = {'protocol':PROTOCOL, 'planned_attempts':len(bindings), 'models':MODELS,
              'settings':SETTINGS, 'concurrency_per_provider':2,
              'dispatch':'fixed rank waves of four, two attempts per provider, wait for wave before next',
              'poll_seconds':10, 'poll_timeout_seconds':60,
              'deepseek_timeout_seconds':7200, 'luna_post_timeout_seconds':120,
              'post_retries':0, 'quality_retries':0, 'tools':False,
              'binding_sha256':sha(canonical(bindings)),
              'timer':'public task read through response parse, verification and comparator; perf_counter in uninterrupted process',
              'resume_timer':'UTC elapsed from original online start includes interruption downtime',
              'warm_start':None, 'reference_used_online':False}
    prepared(root/'CONFIG.json',canonical(config)+b'\n')
    prepared(root/'BINDINGS.json',canonical(bindings)+b'\n')
    say('Prepared and checked',len(bindings),'requests; generation POSTs=0')
    return config, bindings


def extract_response(provider, meta, raw):
    obj=decode(raw)
    text=''; tool=False
    if provider=='deepseek':
        choices=obj.get('choices') or []
        choice=choices[0] if len(choices)==1 else {}
        msg=choice.get('message') or {}
        text=msg.get('content') or ''
        state=choice.get('finish_reason')
        complete=state=='stop'
        tool=bool(msg.get('tool_calls'))
    else:
        outputs=obj.get('output') or []
        text=''.join(part.get('text','') for item in outputs if item.get('type')=='message'
                     for part in item.get('content',[]) if part.get('type') in ('text','output_text'))
        state=obj.get('status')
        complete=state=='completed'
        tool=any(item.get('type') not in ('message','reasoning') for item in outputs)
    identity=obj.get('model')
    identity_ok=str(identity).lower().startswith(MODELS[provider])
    usable=meta.get('http_status')==200 and complete and isinstance(text,str) and bool(text.strip()) and not tool and identity_ok
    return obj,text,state,identity,identity_ok,usable


def systemic_provider_error(meta, obj):
    """Recognize account/quota failures even inside HTTP 200 terminal bodies.

    Per-request output exhaustion lives in incomplete_details and is not a
    reason to stop the batch. Do not inspect that field for systemic errors.
    """
    if meta.get('http_status') in (402,429):
        return 'http_'+str(meta['http_status'])
    error=obj.get('error')
    if not error:
        return None
    details=error if isinstance(error,dict) else {'message':str(error)}
    for field in ('code','type'):
        value=str(details.get(field) or '').strip().lower().replace('-','_').replace(' ','_')
        if any(token in value for token in ('quota','rate_limit','ratelimit','credit_balance','insufficient_credit',
                                           'credit_exhausted','credits_exhausted','insufficient_balance',
                                           'balance_exhausted','billing','payment_required')):
            return value
    message=str(details.get('message') or '').lower()
    if any(token in message for token in ('credit balance','insufficient credit','insufficient balance',
                                         'insufficient quota','quota exceeded','quota has been exceeded',
                                         'rate limit','billing limit','payment required')):
        return 'account_or_rate_limit_message'
    return None


def finish(folder, binding, intent, meta, raw, task, elapsed, resumed):
    generated=elapsed()
    response_received_utc=utc()
    obj,text,state,identity,identity_ok,usable=extract_response(binding['provider'],meta,raw)
    validation_start=time.perf_counter()
    ds=None; score=None; errors=[]
    status='no_answer'
    if usable:
        ds,errors=parse(text,task)
        if errors:
            status='schema_invalid'
        else:
            engine=Engine(task)
            score=engine.verify(ds)
            errors=score['errors']
            status='admissible' if score['admissible'] else 'infeasible'
            if score['admissible']:
                # A one-candidate stream has no competing arrived candidate.
                # Comparator initialization is timed, with no reference access.
                assert compare(score['objective'],score['objective'])==0
    validation_seconds=time.perf_counter()-validation_start
    available=elapsed() if score and score['admissible'] else None
    available_utc=utc() if available is not None else None
    systemic_error=systemic_provider_error(meta,obj)
    result={**binding,'protocol':PROTOCOL,'online_start_utc':intent['online_start_utc'],
            'post_start_utc':intent['post_start_utc'],'response_received_utc':response_received_utc,
            'terminal_utc':utc(),'available_utc':available_utc,'base_url':intent['base_url'],
            'requested_model':MODELS[binding['provider']],'returned_model':identity,
            'identity_accepted':identity_ok,'response_id':obj.get('id'),
            'http_status':meta.get('http_status'),'transport_error':meta.get('error_type'),
            'finish_reason':state,'usage':obj.get('usage'),'error':obj.get('error'),
            'systemic_provider_error':systemic_error,
            'incomplete_details':obj.get('incomplete_details'),'system_fingerprint':obj.get('system_fingerprint'),
            'response_seconds':generated,'available_seconds':available,
            'validation_seconds':validation_seconds,'preparation_seconds':intent['preparation_seconds'],
            'timer_source':'UTC elapsed including downtime' if resumed else 'perf_counter',
            'resumed_after_process_interruption':resumed,
            'usable_text':usable,'raw_text':text if isinstance(text,str) else '',
            'raw_response_sha256':sha(raw) if raw else None,'status':status,
            'admissible':bool(score and score['admissible']),'decisions':ds,
            'objective':score['objective'] if score else None,'errors':errors,
            'metrics':metrics(task,score) if score and score['admissible'] else None,
            'reference_used_online':False}
    if raw is not None and not (folder/'PROVIDER_RAW.json').exists():
        once(folder/'PROVIDER_RAW.json',raw)
    jo(folder/'TERMINAL.json',result)
    say(binding['rank'],binding['attempt_id'],status,'response',round(generated,2),
        'available',round(available,2) if available is not None else None)
    if systemic_error:
        # The immutable terminal and raw response are saved before execute()
        # observes the exception and stops dispatch after the current wave.
        raise RuntimeError('systemic provider error '+systemic_error+'; terminal saved; stop after current wave')
    return result


def attempt(root,binding,key,base,transport=request,poll_seconds=10):
    folder=root/'attempts'/binding['attempt_id']
    terminal=folder/'TERMINAL.json'
    intent_path=folder/'SUBMISSION_INTENT.json'
    if terminal.exists():
        return read(terminal)
    resumed=intent_path.exists()
    if not resumed:
        clock=time.perf_counter()
        online_utc=utc()
        task,body=rebuild_request(binding)
        elapsed=lambda:time.perf_counter()-clock
        intent={**binding,'protocol':PROTOCOL,'online_start_utc':online_utc,
                'post_start_utc':utc(),'base_url':base,'preparation_seconds':elapsed()}
        jo(intent_path,intent)
        say(binding['rank'],binding['attempt_id'],'POST')
        meta,raw=transport('POST',base+('/chat/completions' if binding['provider']=='deepseek' else '/responses'),key,body,
                           7200 if binding['provider']=='deepseek' else 120)
        save_http(folder,'POST',meta,raw)
    else:
        intent=read(intent_path)
        task,_=rebuild_request(binding)
        elapsed=lambda:(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(intent['online_start_utc'])).total_seconds()
        if not (folder/'POST_HTTP.json').exists():
            jo(terminal,{**binding,'protocol':PROTOCOL,'online_start_utc':intent['online_start_utc'],
                         'post_start_utc':intent['post_start_utc'],'terminal_utc':utc(),
                         'usable_text':False,'raw_text':'','status':'uncertain_prior_post',
                         'admissible':False,'objective':None,'available_seconds':None,
                         'response_seconds':None,'finish_reason':'UNCERTAIN_PRIOR_POST_NOT_REPOSTED'})
            raise RuntimeError('uncertain prior POST preserved; no re-POST')
        meta=read(folder/'POST_HTTP.json')
        raw=(folder/'POST_RAW.bin').read_bytes() if (folder/'POST_RAW.bin').exists() else None
    obj=decode(raw)
    if (folder/'PROVIDER_RAW.json').exists():
        return finish(folder,binding,intent,{'http_status':200},(folder/'PROVIDER_RAW.json').read_bytes(),task,elapsed,resumed)
    if binding['provider']=='deepseek' or meta.get('http_status')!=200 or not obj.get('id'):
        result=finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
        if meta.get('http_status')!=200:
            raise RuntimeError('POST error '+str(meta.get('http_status'))+' '+str(meta.get('error_type')))
        if not result['identity_accepted']:
            raise RuntimeError('returned model identity differs; response preserved')
        return result
    response_id=obj['id']
    if not isinstance(response_id,str) or not response_id.startswith('resp_'):
        raise RuntimeError('response ID format')
    if not (folder/'RESPONSE_ID.json').exists():
        jo(folder/'RESPONSE_ID.json',{'response_id':response_id,'saved_utc':utc()})
    polls=sorted(folder.glob('POLL_*_HTTP.json'))
    if polls:
        last=polls[-1]
        poll_raw=last.with_name(last.name.replace('_HTTP.json','_RAW.bin'))
        if poll_raw.exists():
            meta=read(last);raw=poll_raw.read_bytes();obj=decode(raw)
    deadline=time.monotonic()+14400
    errors=0
    while obj.get('status') not in TERMINAL_STATES:
        if time.monotonic()>deadline:
            raise RuntimeError('poll deadline; same response ID retained')
        time.sleep(poll_seconds)
        meta,raw=transport('GET',base+'/responses/'+response_id,key,timeout=60)
        obj=decode(raw)
        save_http(folder,'POLL_'+str(time.time_ns()),meta,raw)
        if systemic_provider_error(meta,obj):
            finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
        if meta.get('http_status')!=200 or not obj:
            errors+=1
            if errors>=3:
                raise RuntimeError('GET failure; same response ID retained')
            continue
        errors=0
        if obj.get('id')!=response_id:
            raise RuntimeError('response ID differs')
    result=finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
    if not result['identity_accepted'] and obj.get('model'):
        raise RuntimeError('returned model identity differs; response preserved')
    return result


def execute(root=DEFAULT_ONLINE, max_rank=None):
    setup_start=time.perf_counter()
    config,bindings=prepare(root)
    lock=(root/'RUN.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0');lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        access={p:credentials(p) for p in MODELS}
        jo(root/'runs'/('RUN_'+str(time.time_ns())+'.json'),
           {'utc':utc(),'protocol':PROTOCOL,'pid':os.getpid(),
            'library_initialization_seconds':LIBRARY_INITIALIZATION_SECONDS,
            'shared_setup_seconds':time.perf_counter()-setup_start,
            'max_rank':max_rank,'per_attempt_preparation_repeated_inside_timer':True})
        bindings=sorted(bindings,key=lambda b:b['rank'])
        failed=False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for wave_start in range(0,len(bindings),4):
                if (root/'PAUSE').exists():
                    say('PAUSED before next wave');break
                batch=[b for b in bindings[wave_start:wave_start+4] if max_rank is None or b['rank']<=max_rank]
                if not batch:
                    continue
                if any(sum(b['provider']==p for b in batch)>2 for p in MODELS):
                    raise RuntimeError('frozen wave violates provider concurrency')
                jobs={pool.submit(attempt,root,b,*access[b['provider']]):b for b in batch}
                for future,b in jobs.items():
                    try:
                        future.result()
                    except Exception as exc:
                        reason=str(exc)
                        for key,base in access.values():
                            reason=reason.replace(key,'[REDACTED]')
                        jo(root/'alerts'/f"{b['attempt_id']}_{time.time_ns()}.json",{'utc':utc(),'attempt_id':b['attempt_id'],'reason':reason})
                        say('PAUSED',b['attempt_id'],reason)
                        failed=True
                if failed:
                    break
        return 2 if failed else 0
    finally:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--root',type=Path,default=DEFAULT_ONLINE)
    p.add_argument('--max-rank',type=int)
    a=p.parse_args()
    if a.prepare:
        prepare(a.root)
    if a.execute:
        raise SystemExit(execute(a.root,a.max_rank))
