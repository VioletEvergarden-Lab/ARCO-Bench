"""One formal attempt per task/model, durable bodies and no automatic re-POST."""
import argparse
import concurrent.futures
import copy
import datetime as dt
import hashlib
import json
import msvcrt
import os
import random
import threading
import time
from pathlib import Path
from study_common import HERE,P,read,write
from provider_transport import MODELS,credentials,request,utc

ANCHORS=[4,3,1,2,5,6,12,7,8,9,10,24]
SYSTEM='You are solving a UAV integrated-repair optimization task. Return only one JSON object that exactly follows the requested schema. Do not use Markdown or explanatory text.'
SETTINGS={'deepseek':{'max_tokens':128000,'model':'deepseek-v4-pro','temperature':0.0},'luna':{'background':True,'max_output_tokens':128000,'model':'gpt-5.6-luna','reasoning':{'context':'current_turn','effort':'max','mode':'standard'},'store':False,'stream':False,'tools':[]}}
TERMINAL_STATES={'completed','failed','cancelled','incomplete'}
PRINT_LOCK=threading.Lock()

def canonical(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def sha(data): return hashlib.sha256(data).hexdigest()
def once(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as file: file.write(data); file.flush(); os.fsync(file.fileno())
def jo(path,obj): once(path,canonical(obj)+b'\n')
def prepared(path,data):
    if path.exists():
        if path.read_bytes()!=data: raise RuntimeError('prepared input differs '+str(path))
    else: once(path,data)
def say(*args):
    with PRINT_LOCK: print(*args,flush=True)
def prepare(pilot=False):
    root=HERE/('online_pilot' if pilot else 'online'); records=[]
    if pilot:
        paths=sorted((HERE/'networks/pilots/tasks').glob('PILOT_S*_A.json')); assert paths
        records=[('network',read(paths[0]))]
    else:
        paths=sorted((HERE/'networks/tasks').glob('NET_*.json')); assert len(paths)==36
        for path in paths:
            task=read(path); reference=read(HERE/'networks/references'/path.name); assert reference['optimal']
            records.append(('network',task))
        records += [('core_anchor',read(P/'data/public/records'/f'CA12_CORE_{i:03d}.json')) for i in ANCHORS]
        random.Random(73009).shuffle(records)
    instruction_network=(HERE/'continuous_public_instructions.md').read_text(encoding='utf-8')
    instruction_core=(P/'prompts/complete_public_instructions.md').read_text(encoding='utf-8')
    opaque_network_ids={}
    network_ids=sorted(task['record_id'] for layer,task in records if layer=='network')
    random.Random(73117).shuffle(network_ids)
    opaque_network_ids={rid:f'NET_{i:03d}' for i,rid in enumerate(network_ids,1)} if not pilot else {rid:rid for rid in network_ids}
    bindings=[]
    for rank,(layer,task) in enumerate(records,1):
        rid=task['record_id']; public_task=copy.deepcopy(task)
        public_task['record_id']=opaque_network_ids.get(rid,rid)
        if layer=='network': public_task['model'].pop('slot_min',None)
        user=(instruction_core if layer=='core_anchor' else instruction_network)+'\n\nPublic task:\n\n'+canonical(public_task).decode('utf-8')
        # Even one-byte-per-token is a conservative upper bound for this ASCII
        # prompt. Reserving all 128000 output tokens fits both official contexts.
        upper_tokens=len(user.encode())+len(SYSTEM.encode())
        assert upper_tokens+128000<1_000_000
        prepared(root/'public_inputs'/f'{rid}.txt',user.encode('utf-8'))
        for provider in MODELS:
            body=copy.deepcopy(SETTINGS[provider]); key='messages' if provider=='deepseek' else 'input'
            body[key]=([{'role':'system','content':SYSTEM}] if provider=='deepseek' else [])+[{'role':'user','content':user}]
            data=canonical(body); rel=f'{provider}/requests/{rid}.json'; prepared(root/rel,data)
            bindings.append({'record_id':rid,'public_record_id':public_task['record_id'],'provider':provider,'layer':layer,'rank':rank,'request_path':rel,'request_sha256':sha(data),'user_sha256':sha(user.encode()),'input_byte_upper_bound_tokens':upper_tokens})
    config={'prepared_utc':utc(),'pilot':pilot,'tasks_per_provider':len(records),'planned_generations':len(bindings),'models':MODELS,'generation_parameters':SETTINGS,'concurrency_per_provider':1 if pilot else 4,'order_seed':73009,'anchor_ids':[f'CA12_CORE_{i:03d}' for i in ANCHORS] if not pilot else [],'instruction_network_sha256':sha(instruction_network.encode()),'instruction_core_sha256':sha(instruction_core.encode()),'same_user_content':True,'quality_retries':0,'tools':False,'post_retries':0,'json_response_format_field':'not specified, same as archived complete-public requests','source_settings':'arco_core72_complete_public_rules_deepseek_luna_20260922_v1/provider/CONFIG.json','context_sources':{'luna':'https://developers.openai.com/api/docs/models/gpt-5.6-luna','deepseek':'https://api-docs.deepseek.com/quick_start/pricing/'}}
    if not (root/'CONFIG.json').exists(): jo(root/'CONFIG.json',config)
    prepared(root/'BINDINGS.json',canonical(bindings)+b'\n'); say('Prepared',len(bindings),'pilot' if pilot else 'formal','requests; generation POSTs=0')

def decode(raw):
    try: return json.loads(raw) if raw else {}
    except ValueError: return {}
def save_http(folder,stem,meta,raw):
    jo(folder/(stem+'_HTTP.json'),meta)
    if raw is not None: once(folder/(stem+'_RAW.bin'),raw)
def finish(folder,b,intent,meta,raw):
    obj=decode(raw); provider=b['provider']; text=''; tool=False
    if provider=='deepseek':
        choices=obj.get('choices') or []; choice=choices[0] if len(choices)==1 else {}; msg=choice.get('message') or {}; text=msg.get('content') or ''; state=choice.get('finish_reason'); complete=state=='stop'; tool=bool(msg.get('tool_calls'))
    else:
        outputs=obj.get('output') or []; text=''.join(part.get('text','') for item in outputs if item.get('type')=='message' for part in item.get('content',[]) if part.get('type') in ('text','output_text')); state=obj.get('status'); complete=state=='completed'; tool=any(item.get('type') not in ('message','reasoning') for item in outputs)
    identity=obj.get('model'); normalized=str(identity).lower()
    identity_ok=normalized.startswith(MODELS[provider]) or (provider=='deepseek' and normalized.startswith('deepseek-v4-pro'))
    usable=meta.get('http_status')==200 and complete and isinstance(text,str) and bool(text.strip()) and not tool and identity_ok
    result={**b,'post_start_utc':intent['post_start_utc'],'terminal_utc':utc(),'base_url':intent['base_url'],'requested_model':MODELS[provider],'returned_model':identity,'identity_accepted':identity_ok,'response_id':obj.get('id'),'http_status':meta.get('http_status'),'transport_error':meta.get('error_type'),'finish_reason':state,'usage':obj.get('usage'),'error':obj.get('error'),'incomplete_details':obj.get('incomplete_details'),'system_fingerprint':obj.get('system_fingerprint'),'latency_seconds':(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(intent['post_start_utc'])).total_seconds(),'usable_text':usable,'raw_text':text if isinstance(text,str) else '', 'raw_response_sha256':sha(raw) if raw else None}
    if raw is not None and not (folder/'PROVIDER_RAW.json').exists(): once(folder/'PROVIDER_RAW.json',raw)
    jo(folder/'TERMINAL.json',result); say(provider,b['rank'],b['record_id'],state,identity,'seconds',round(result['latency_seconds'],1),'usable',usable)
    return result
def attempt(root,b,key,base):
    provider=b['provider']; folder=root/provider/'attempts'/b['record_id']; terminal=folder/'TERMINAL.json'; intent_path=folder/'SUBMISSION_INTENT.json'
    if terminal.exists(): return read(terminal)
    if not intent_path.exists():
        body=(root/b['request_path']).read_bytes(); assert sha(body)==b['request_sha256']
        intent={**b,'post_start_utc':utc(),'base_url':base}; jo(intent_path,intent)
        say(provider,b['rank'],b['record_id'],'POST')
        meta,raw=request('POST',base+('/chat/completions' if provider=='deepseek' else '/responses'),key,body,7200 if provider=='deepseek' else 120)
        save_http(folder,'POST',meta,raw)
    else:
        intent=read(intent_path)
        if not (folder/'POST_HTTP.json').exists():
            jo(terminal,{**b,'post_start_utc':intent['post_start_utc'],'terminal_utc':utc(),'usable_text':False,'raw_text':'','finish_reason':'UNCERTAIN_PRIOR_POST_NOT_REPOSTED'}); raise RuntimeError('uncertain prior POST; retained without re-POST')
        meta=read(folder/'POST_HTTP.json'); raw=(folder/'POST_RAW.bin').read_bytes() if (folder/'POST_RAW.bin').exists() else None
    obj=decode(raw)
    if (folder/'PROVIDER_RAW.json').exists(): return finish(folder,b,intent,{'http_status':200},(folder/'PROVIDER_RAW.json').read_bytes())
    if provider=='deepseek' or meta.get('http_status')!=200 or not obj.get('id'):
        result=finish(folder,b,intent,meta,raw)
        if meta.get('http_status')!=200: raise RuntimeError('POST error '+str(meta.get('http_status'))+' '+str(meta.get('error_type')))
        if not result['identity_accepted']: raise RuntimeError('returned identity differs; preserved')
        return result
    response_id=obj['id']; assert isinstance(response_id,str) and response_id.startswith('resp_')
    if not (folder/'RESPONSE_ID.json').exists(): jo(folder/'RESPONSE_ID.json',{'response_id':response_id,'saved_utc':utc()})
    # Recover the latest same-ID poll after interruption; no duplicate generation.
    polls=sorted(folder.glob('POLL_*_HTTP.json'))
    if polls:
        meta=read(polls[-1]); candidate=polls[-1].with_name(polls[-1].name.replace('_HTTP.json','_RAW.bin'))
        if candidate.exists(): raw=candidate.read_bytes(); obj=decode(raw)
    deadline=time.monotonic()+14400; errors=0
    while obj.get('status') not in TERMINAL_STATES:
        if time.monotonic()>deadline: raise RuntimeError('poll deadline; same response ID retained')
        time.sleep(10); meta,raw=request('GET',base+'/responses/'+response_id,key,timeout=60); obj=decode(raw); save_http(folder,'POLL_'+str(time.time_ns()),meta,raw)
        if meta.get('http_status')!=200 or not obj:
            errors+=1
            if errors>=3: raise RuntimeError('GET failure; same response ID retained')
            continue
        errors=0
        if obj.get('id')!=response_id: raise RuntimeError('response ID differs')
    return finish(folder,b,intent,meta,raw)
def execute(pilot=False,provider=None):
    root=HERE/('online_pilot' if pilot else 'online'); config=read(root/'CONFIG.json'); bindings=read(root/'BINDINGS.json'); names=[provider] if provider else list(MODELS); stop=threading.Event()
    lock=(root/'RUN.lock').open('a+b'); lock.seek(0)
    if not lock.read(1): lock.write(b'0'); lock.flush()
    lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    access={p:credentials(p) for p in names}; concurrency=config['concurrency_per_provider']
    def worker(p,slot):
        rows=sorted((b for b in bindings if b['provider']==p),key=lambda b:b['rank'])[slot::concurrency]; key,base=access[p]
        for b in rows:
            if stop.is_set(): return
            try: attempt(root,b,key,base)
            except Exception as exc:
                reason=str(exc).replace(key,'[REDACTED]'); jo(root/'alerts'/f'{p}_{time.time_ns()}.json',{'utc':utc(),'record_id':b['record_id'],'reason':reason}); say('PAUSED',p,b['record_id'],reason); stop.set(); return
    try:
        write(root/'PROCESS.json',{'pid':os.getpid(),'started_utc':utc()})
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)*concurrency) as pool:
            futures=[pool.submit(worker,p,slot) for p in names for slot in range(concurrency)]
            for future in futures: future.result()
    finally: lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1); lock.close()
    return 2 if stop.is_set() else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--prepare',action='store_true'); parser.add_argument('--execute',action='store_true'); parser.add_argument('--pilot',action='store_true'); parser.add_argument('--provider',choices=list(MODELS)); args=parser.parse_args()
    if args.prepare: prepare(args.pilot)
    if args.execute: raise SystemExit(execute(args.pilot,args.provider))
