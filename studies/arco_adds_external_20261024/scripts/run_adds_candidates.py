"""Frozen ADDS first-request evaluation with durable no-rePOST semantics.

Prepare reconstructs and hashes inputs but performs no HTTP request. Execute is
the only generation gate. No reference file is read in preparation or execution.
"""
from pathlib import Path
from urllib.parse import urlsplit
from collections import Counter
import argparse, concurrent.futures, copy, datetime as dt, hashlib, json, os, sys, threading, time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'runtime'))
from provider_transport import MODELS,credentials,request,utc

PROTOCOL='adds_first_requests_v1_20261025'
SYSTEM='You are solving a UAV integrated-repair optimization task. Return only one JSON object that exactly follows the requested schema. Do not use Markdown or explanatory text.'
SETTINGS={'deepseek':{'max_tokens':128000,'model':'deepseek-v4-pro','temperature':0.0},
 'luna':{'background':True,'max_output_tokens':128000,'model':'gpt-5.6-luna',
         'reasoning':{'context':'current_turn','effort':'max','mode':'standard'},'store':False,'stream':False,'tools':[]}}
TERMINAL_STATES={'completed','failed','cancelled','incomplete'}
ONLINE=ROOT/'runs/generation'
PRINT_LOCK=threading.Lock()
_CE=None

def runtime():
    global _CE
    if _CE is None:
        from adds_runtime import load_runtime
        _CE,*_=load_runtime()
    return _CE

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def once(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def jo(path,x):once(path,canonical(x)+b'\n')
def prepared(path,data):
    path=Path(path)
    if path.exists():
        if path.read_bytes()!=data:raise RuntimeError('frozen content differs: '+str(path))
    else:once(path,data)
def say(*args):
    with PRINT_LOCK:print(*args,flush=True)
def decode(raw):
    try:return json.loads(raw) if raw else {}
    except (ValueError,TypeError):return {}
def save_http(folder,name,meta,raw):
    if raw is not None:once(folder/(name+'_RAW.bin'),raw)
    jo(folder/(name+'_HTTP.json'),meta)
def local(path):
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT.resolve()):raise ValueError('input or output outside study')
    return p

def public_request(item,public_id,provider,instructions):
    p=local(item['task_path']);data=p.read_bytes()
    if sha(data)!=item['sha256']:raise RuntimeError('frozen task hash differs: '+item['record_id'])
    task=decode(data)
    if task.get('record_id')!=item['record_id']:raise RuntimeError('task identity differs')
    task=copy.deepcopy(task);task['record_id']=public_id
    task['model'].pop('slot_min',None)
    user=instructions+'\n\nPublic task:\n\n'+canonical(task).decode('utf-8')
    body=copy.deepcopy(SETTINGS[provider]);key='messages' if provider=='deepseek' else 'input'
    body[key]=([{'role':'system','content':SYSTEM}] if provider=='deepseek' else [])+[{'role':'user','content':user}]
    return task,user,canonical(body)

def prepare(root=ONLINE,freeze=ROOT/'instances/FROZEN.json'):
    root=local(Path(root).resolve().relative_to(ROOT.resolve()))
    freeze=Path(freeze).resolve();frozen=read(freeze)
    if frozen.get('frozen') is not True:raise RuntimeError('formal instances are not frozen')
    items=frozen['tasks']
    if not items or len({i['record_id'] for i in items})!=len(items):raise RuntimeError('empty or duplicate formal tasks')
    instruction_path=ROOT/'source/ADDS_public_instructions.md'
    instructions=instruction_path.read_text(encoding='utf-8')
    if MODELS!={p:s['model'] for p,s in SETTINGS.items()}:raise RuntimeError('model settings and transport identity differ')
    bindings=[]
    for index,item in enumerate(sorted(items,key=lambda x:x['record_id']),1):
        for provider in ('deepseek','luna'):
            public_id=f'ADDS_{index:03d}'
            task,user,body=public_request(item,public_id,provider,instructions)
            if any(k in task for k in ('reference','reference_plan','optimal_plan','target_witness')):
                raise RuntimeError('reference field in public task')
            aid=f"{item['record_id']}__{provider}__r1"
            req=root/'prepared'/f'{aid}.json'
            prepared(req,body)
            bindings.append(dict(rank=len(bindings)+1,attempt_id=aid,provider=provider,repeat=1,
                record_id=item['record_id'],public_record_id=public_id,task_path=item['task_path'],task_sha256=item['sha256'],
                base_id=item.get('base_id'),condition=item.get('condition'),
                request_path=req.relative_to(ROOT).as_posix(),request_sha256=sha(body),public_payload_sha256=sha(user.encode('utf-8'))))
    config=dict(protocol=PROTOCOL,planned_conditions=len(items),planned_attempts=len(bindings),models=MODELS,settings=SETTINGS,
       freeze_path=freeze.relative_to(ROOT).as_posix(),freeze_sha256=sha(freeze.read_bytes()),
       instruction_path=instruction_path.relative_to(ROOT).as_posix(),instruction_sha256=sha(instruction_path.read_bytes()),
       binding_sha256=sha(canonical(bindings)),first_requests_only=True,post_retries=0,quality_retries=0,
       concurrency_per_provider=2,dispatch='fixed rank waves of four, at most two per provider; finish a wave before starting next',
       poll_seconds=10,poll_timeout_seconds=60,deepseek_timeout_seconds=7200,luna_post_timeout_seconds=120,
       reference_used_online=False,tools=False,warm_start=None,
       timer='task read and prompt reconstruction through parse and independent validation; shared imports/credentials excluded',
       resume_timer='elapsed UTC from original online start, including interruption downtime')
    config['runtime_sources']=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p.read_bytes())) for p in
      [ROOT/'scripts/adds_runtime.py',ROOT/'runtime/base_engine.py',ROOT/'runtime/continuous_engine.py',ROOT/'runtime/model_parameters.json']]
    prepared(root/'CONFIG.json',canonical(config)+b'\n')
    prepared(root/'BINDINGS.json',canonical(bindings)+b'\n')
    say('PREPARED',len(items),'conditions',len(bindings),'first requests; generation POSTs=0')
    return config,bindings

def rebuild(binding,config):
    for item in config.get('runtime_sources',[]):
        if sha(local(item['path']).read_bytes())!=item['sha256']:raise RuntimeError('frozen verification runtime changed')
    instructions=local(config['instruction_path']).read_text(encoding='utf-8')
    if sha(local(config['instruction_path']).read_bytes())!=config['instruction_sha256']:raise RuntimeError('instructions changed')
    item=dict(record_id=binding['record_id'],task_path=binding['task_path'],sha256=binding['task_sha256'])
    task,user,body=public_request(item,binding['public_record_id'],binding['provider'],instructions)
    if sha(body)!=binding['request_sha256'] or sha(user.encode('utf-8'))!=binding['public_payload_sha256']:
        raise RuntimeError('request reconstruction changed')
    if local(binding['request_path']).read_bytes()!=body:raise RuntimeError('prepared request changed')
    return task,body

def effective_bindings(root,bindings,offline=False):
    """Apply only explicitly authorized, terminal zero-generation replacements.

    Frozen logical requests and their bodies remain unchanged. A replacement is
    a new transport attempt for a failed billing operation, never a quality retry.
    """
    mapping=root/'REPLACEMENTS.json';export=root/'EFFECTIVE_BINDINGS.json'
    if offline and export.exists():
        effective=read(export);original={b['rank']:b for b in bindings}
        if len(effective)!=len(bindings) or len({b['rank'] for b in effective})!=len(bindings):
            raise RuntimeError('effective evidence binding count differs')
        for b in effective:
            before=original[b['rank']];stripped={k:v for k,v in b.items() if k not in
                ('logical_attempt_id','replaces_operational_attempt','replacement_request_sha256')}
            if b['attempt_id']!=before['attempt_id']:
                if b['attempt_id']!=before['attempt_id']+'__transport2' or b.get('logical_attempt_id')!=before['attempt_id']:
                    raise RuntimeError('invalid effective transport identity')
                stripped['attempt_id']=before['attempt_id']
            if stripped!=before:raise RuntimeError('effective evidence changed frozen request binding')
        return effective
    if not mapping.exists():
        if export.exists() and read(export)!=bindings:
            raise RuntimeError('sanitized evidence bundle is offline-only; live execution needs local replacement authorization')
        return bindings
    policy=read(mapping)
    if policy.get('authorization')!='user_20261026_zero_generation_credit_failures':
        raise RuntimeError('replacement policy lacks explicit recorded authorization')
    replacements=policy['replacements'];by={b['attempt_id']:b for b in bindings}
    if len({r['original_attempt_id'] for r in replacements})!=len(replacements):raise RuntimeError('duplicate replacement')
    updated={}
    for r in replacements:
        old=r['original_attempt_id'];b=by[old];new=r['replacement_attempt_id']
        if b['provider']!='luna' or new!=old+'__transport2':raise RuntimeError('unapproved replacement identity')
        folder=root/'attempts'/old;terminal=folder/'TERMINAL.json';t=read(terminal)
        raw=decode((folder/'PROVIDER_RAW.json').read_bytes())
        if sha(terminal.read_bytes())!=r['original_terminal_sha256'] or b['request_sha256']!=r['request_sha256']:
            raise RuntimeError('replacement evidence or body hash differs')
        if not (t.get('finish_reason')=='failed' and t.get('systemic_provider_error')=='credit_balance_exhausted'
            and not t.get('usable_text') and not t.get('raw_text') and t.get('decisions') is None
            and not raw.get('output') and raw.get('usage') is None):
            raise RuntimeError('replacement is not a terminal zero-generation credit failure')
        updated[old]={**b,'attempt_id':new,'logical_attempt_id':old,
            'replaces_operational_attempt':old,'replacement_request_sha256':b['request_sha256']}
    result=[updated.get(b['attempt_id'],b) for b in bindings]
    if len({b['attempt_id'] for b in result})!=len(result):raise RuntimeError('duplicate effective attempts')
    return result

def systemic_error(meta,obj):
    if meta.get('http_status') in (402,429):return 'http_'+str(meta['http_status'])
    e=obj.get('error') or {};e=e if isinstance(e,dict) else {'message':str(e)}
    for field in ('code','type'):
        s=str(e.get(field) or '').lower().replace('-','_')
        if any(t in s for t in ('quota','rate_limit','ratelimit','credit_balance','insufficient_credit','credit_exhausted','credits_exhausted','insufficient_balance','balance_exhausted','billing','payment_required')):return s
    s=str(e.get('message') or '').lower()
    if any(t in s for t in ('credit balance','insufficient credit','insufficient balance','insufficient quota','quota exceeded','rate limit','billing limit','payment required')):return 'account_or_rate_error'
    return None

def extract(provider,meta,raw):
    obj=decode(raw);text='';tool=False
    if provider=='deepseek':
        choices=obj.get('choices') or [];choice=choices[0] if len(choices)==1 else {};msg=choice.get('message') or {}
        text=msg.get('content') or '';state=choice.get('finish_reason');complete=state=='stop';tool=bool(msg.get('tool_calls'))
    else:
        outputs=obj.get('output') or []
        text=''.join(p.get('text','') for i in outputs if i.get('type')=='message' for p in i.get('content',[]) if p.get('type') in ('text','output_text'))
        state=obj.get('status');complete=state=='completed';tool=any(i.get('type') not in ('message','reasoning') for i in outputs)
    identity=obj.get('model');ok=str(identity).lower().startswith(MODELS[provider])
    usable=meta.get('http_status')==200 and complete and bool(isinstance(text,str) and text.strip()) and not tool and ok
    return obj,text,state,identity,ok,usable

def finish(folder,binding,intent,meta,raw,task,elapsed,resumed):
    received=elapsed();received_utc=utc();obj,text,state,identity,identity_ok,usable=extract(binding['provider'],meta,raw)
    start=time.perf_counter();ds=score=None;errors=[];status='no_answer'
    if usable:
        ce=runtime();ds,errors=ce.parse(text,task)
        if errors:status='schema_invalid'
        else:
            score=ce.Engine(task).verify(ds);errors=score['errors'];status='admissible' if score['admissible'] else 'infeasible'
            if any(e.startswith('SCHEMA_') for e in errors):status='schema_invalid'
            if score['admissible']:assert ce.compare(score['objective'],score['objective'])==0
    elif meta.get('http_status')!=200:status='request_failed'
    available=elapsed() if score and score['admissible'] else None
    submission=('accepted' if intent.get('accepted_response_id') or meta.get('http_status')==200 else
                'uncertain_delivery' if meta.get('http_status') is None or meta.get('http_status',0)>=500 else 'rejected')
    result={**binding,'protocol':PROTOCOL,'online_start_utc':intent['online_start_utc'],'post_start_utc':intent['post_start_utc'],
      'terminal_utc':utc(),'response_received_utc':received_utc,'available_utc':utc() if available is not None else None,
      'base_url':intent['base_url'],'requested_model':MODELS[binding['provider']],'returned_model':identity,
      'identity_accepted':identity_ok,'response_id':obj.get('id') or intent.get('accepted_response_id'),
      'http_status':meta.get('http_status'),'transport_error':meta.get('error_type'),'submission_state':submission,
      'finish_reason':state,'usage':obj.get('usage'),'error':obj.get('error'),'incomplete_details':obj.get('incomplete_details'),
      'systemic_provider_error':systemic_error(meta,obj),'system_fingerprint':obj.get('system_fingerprint'),
      'response_seconds':received,'available_seconds':available,'validation_seconds':time.perf_counter()-start,
      'preparation_seconds':intent['preparation_seconds'],'timer_source':'elapsed UTC including downtime' if resumed else 'perf_counter',
      'resumed_after_process_interruption':resumed,'usable_text':usable,'raw_text':text if isinstance(text,str) else '',
      'raw_response_sha256':sha(raw) if raw else None,'status':status,'admissible':bool(score and score['admissible']),
      'decisions':ds,'objective':score['objective'] if score else None,'errors':errors,'reference_used_online':False}
    if not (folder/'PROVIDER_HTTP.json').exists():jo(folder/'PROVIDER_HTTP.json',meta)
    if raw is not None and not (folder/'PROVIDER_RAW.json').exists():once(folder/'PROVIDER_RAW.json',raw)
    jo(folder/'TERMINAL.json',result)
    say(binding['rank'],binding['attempt_id'],status,'response',round(received,2),'available',round(available,2) if available is not None else None)
    if result['systemic_provider_error']:raise RuntimeError('systemic provider error; terminal saved; stop dispatch')
    return result

def attempt(root,binding,config,key,base,transport=request,poll_seconds=10):
    folder=root/'attempts'/binding['attempt_id'];terminal=folder/'TERMINAL.json';ip=folder/'SUBMISSION_INTENT.json'
    if terminal.exists():return read(terminal)
    resumed=ip.exists()
    if not resumed:
        clock=time.perf_counter();started=utc();task,body=rebuild(binding,config);elapsed=lambda:time.perf_counter()-clock
        intent={**binding,'protocol':PROTOCOL,'online_start_utc':started,'post_start_utc':utc(),'base_url':base,'preparation_seconds':elapsed()}
        jo(ip,intent);say(binding['rank'],binding['attempt_id'],'POST')
        meta,raw=transport('POST',base+('/chat/completions' if binding['provider']=='deepseek' else '/responses'),key,body,7200 if binding['provider']=='deepseek' else 120)
        save_http(folder,'POST',meta,raw)
    else:
        intent=read(ip);task,_=rebuild(binding,config)
        elapsed=lambda:(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(intent['online_start_utc'])).total_seconds()
        if not (folder/'POST_HTTP.json').exists():
            jo(terminal,{**binding,'protocol':PROTOCOL,'status':'uncertain_prior_post','submission_state':'uncertain_delivery',
               'online_start_utc':intent['online_start_utc'],'terminal_utc':utc(),'usable_text':False,'admissible':False,
               'objective':None,'decisions':None,'available_seconds':None,'finish_reason':'UNCERTAIN_PRIOR_POST_NOT_REPOSTED'})
            raise RuntimeError('uncertain prior POST preserved; no re-POST')
        meta=read(folder/'POST_HTTP.json');raw=(folder/'POST_RAW.bin').read_bytes() if (folder/'POST_RAW.bin').exists() else None
    obj=decode(raw)
    if (folder/'PROVIDER_RAW.json').exists():
        if not (folder/'PROVIDER_HTTP.json').exists():raise RuntimeError('saved response metadata missing; preserve attempt for review')
        if (folder/'RESPONSE_ID.json').exists():intent['accepted_response_id']=read(folder/'RESPONSE_ID.json')['response_id']
        return finish(folder,binding,intent,read(folder/'PROVIDER_HTTP.json'),(folder/'PROVIDER_RAW.json').read_bytes(),task,elapsed,resumed)
    if binding['provider']=='deepseek' or meta.get('http_status')!=200 or not obj.get('id'):
        result=finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
        if meta.get('http_status')!=200:raise RuntimeError('POST transport/HTTP failure; no re-POST')
        if not result['identity_accepted']:raise RuntimeError('returned model identity differs; response retained')
        return result
    response_id=obj['id']
    if not isinstance(response_id,str) or not response_id.startswith('resp_'):raise RuntimeError('invalid response ID; original POST retained')
    intent['accepted_response_id']=response_id
    if not (folder/'RESPONSE_ID.json').exists():jo(folder/'RESPONSE_ID.json',dict(response_id=response_id,saved_utc=utc()))
    polls=sorted(folder.glob('POLL_*_HTTP.json'))
    if polls:
        last=polls[-1];pr=last.with_name(last.name.replace('_HTTP.json','_RAW.bin'))
        if pr.exists():
            pm=read(last);po=decode(pr.read_bytes())
            if pm.get('http_status')==200 and po.get('id')==response_id:meta,raw,obj=pm,pr.read_bytes(),po
    deadline=time.monotonic()+14400;errors=0
    while obj.get('status') not in TERMINAL_STATES:
        if time.monotonic()>deadline:raise RuntimeError('poll deadline; accepted response retained for GET-only recovery')
        time.sleep(poll_seconds);meta,raw=transport('GET',base+'/responses/'+response_id,key,timeout=60);obj=decode(raw)
        save_http(folder,'POLL_'+str(time.time_ns()),meta,raw)
        if systemic_error(meta,obj):
            if obj.get('id')==response_id and obj.get('status') in TERMINAL_STATES:
                finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
            raise RuntimeError('GET account/rate error; accepted response retained for GET-only recovery')
        if meta.get('http_status')!=200 or not obj:
            errors+=1
            if errors>=3:raise RuntimeError('GET unavailable; accepted response retained for GET-only recovery')
            continue
        errors=0
        if obj.get('id')!=response_id:raise RuntimeError('GET response ID differs; original ID retained')
    result=finish(folder,binding,intent,meta,raw,task,elapsed,resumed)
    if not result['identity_accepted'] and obj.get('model'):raise RuntimeError('returned model identity differs; response retained')
    return result

def execute(root=ONLINE,freeze=ROOT/'instances/FROZEN.json',max_rank=None,providers=('deepseek','luna')):
    if (root/'DELIVERY_READ_ONLY.json').exists() or (ROOT/'DELIVERY_READ_ONLY.json').exists():
        raise RuntimeError('Read-only research evidence delivery: generation is disabled. Use score/diagnose/replay; prepare new research in a new directory.')
    import msvcrt
    setup=time.perf_counter();runtime();config,bindings=prepare(root,freeze)
    bindings=effective_bindings(root,bindings)
    lock=(root/'RUN.lock').open('a+b');lock.seek(0)
    if not lock.read(1):lock.write(b'0');lock.flush()
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        access={p:credentials(p) for p in providers}
        jo(root/'executions'/('RUN_'+str(time.time_ns())+'.json'),dict(utc=utc(),pid=os.getpid(),protocol=PROTOCOL,
           providers=list(providers),max_rank=max_rank,shared_setup_seconds=time.perf_counter()-setup,
           replacements_sha256=sha((root/'REPLACEMENTS.json').read_bytes()) if (root/'REPLACEMENTS.json').exists() else None))
        failed=False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for offset in range(0,len(bindings),4):
                if (root/'PAUSE').exists():say('PAUSED before next wave');break
                batch=[b for b in bindings[offset:offset+4] if b['provider'] in providers and (max_rank is None or b['rank']<=max_rank)]
                if any(sum(b['provider']==p for b in batch)>2 for p in providers):raise RuntimeError('provider concurrency exceeded')
                jobs={pool.submit(attempt,root,b,config,*access[b['provider']]):b for b in batch}
                for future,b in jobs.items():
                    try:future.result()
                    except Exception as exc:
                        reason=str(exc)
                        for key,base in access.values():reason=reason.replace(key,'[REDACTED]')
                        jo(root/'alerts'/f"{b['attempt_id']}_{time.time_ns()}.json",dict(utc=utc(),attempt_id=b['attempt_id'],reason=reason))
                        say('PAUSED',b['attempt_id'],reason);failed=True
                if failed:break
        return 2 if failed else 0
    finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--root',type=Path,default=ONLINE);parser.add_argument('--freeze',type=Path,default=ROOT/'instances/FROZEN.json')
    parser.add_argument('--max-rank',type=int);parser.add_argument('--providers',nargs='+',choices=list(MODELS),default=list(MODELS))
    args=parser.parse_args()
    if args.prepare:prepare(args.root.resolve(),args.freeze.resolve())
    if args.execute:raise SystemExit(execute(args.root.resolve(),args.freeze.resolve(),args.max_rank,args.providers))
