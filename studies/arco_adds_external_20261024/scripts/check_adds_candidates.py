"""Transport/recovery checks with mock responses; no credentials or real HTTP."""
from pathlib import Path
from unittest.mock import patch
import copy,hashlib,json,socket,time
import run_adds_candidates as runner
ROOT=runner.ROOT

def main():
    # Small archived input supplies geometry only; this is never a formal case.
    source=ROOT/'runtime/fixtures/mock_incumbent_task.json'
    task=runner.read(source);hub=task['fleet'][0]['initial_vertiport']
    task['timing'].update(departure_grid_min=.5,turnaround_min=0.,load_min=5/60,unload_min=5/60,max_charge_blocks=0)
    task['intervention']={'resource_intervals':[],'initial_soc_overrides':{}}
    task['resources']['pad']={k:20 for k in task['resources']['pad']}
    task['resources']['corridor']={k:20 for k in task['resources']['corridor']}
    for m in task['missions']:
        m['incoming']=None;m['release_min']=0;m['due_min']=120
        c=next(c for c in task['corridors'] if c['origin']==m['destination'] and c['destination']==hub)
        m['return_path']={'path_id':'RETURN','origin':m['destination'],'destination':hub,'corridor_ids':[c['corridor_id']]}
    root=ROOT/'runs/mock_pipeline'/str(time.time_ns());root.mkdir(parents=True)
    tasks=[]
    for i in range(3):
        t=copy.deepcopy(task);t['record_id']=f'MOCK_ADDS_{i+1:02d}'
        p=root/f'task_{i+1}.json';runner.jo(p,t)
        tasks.append(dict(record_id=t['record_id'],task_path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),base_id='mock',condition='mock'))
    freeze=root/'FROZEN.json';runner.jo(freeze,{'frozen':True,'scope':'mock transport only, not a formal selection','tasks':tasks})
    online=root/'prepared_fixture';config,bindings=runner.prepare(online,freeze)
    original=runner.attempt;ce=runner.runtime()
    calls=[]
    def response(binding,queued=False,failed=False):
        task,_=runner.rebuild(binding,config);plan=ce.Engine(task).greedy();score=ce.Engine(task).verify(plan)
        assert score['admissible'] and score['objective']['total_holds']==0
        content=json.dumps({'record_id':task['record_id'],'decisions':plan})
        if binding['provider']=='deepseek':
            return {'model':'deepseek-v4-pro','id':'mock_ds','choices':[{'finish_reason':'stop','message':{'content':content}}]}
        return {'model':'gpt-5.6-luna','id':'resp_mock_'+str(binding['rank']),'status':'queued' if queued else 'failed' if failed else 'completed',
                'error':{'code':'credit_balance_exhausted','message':'Credit balance exhausted'} if failed else None,
                'output':[] if queued or failed else [{'type':'message','content':[{'type':'output_text','text':content}]}]}
    def fake_for(binding):
        def transport(method,url,key,body=None,timeout=60):
            calls.append((binding['attempt_id'],method))
            return {'http_status':200,'mock':True},json.dumps(response(binding)).encode()
        return transport
    d,l=bindings[:2]
    r=original(root/'success',d,config,'MOCK','https://api.deepseek.com',transport=fake_for(d),poll_seconds=0)
    assert r['admissible'] and r['submission_state']=='accepted' and r['available_seconds']>=r['response_seconds']
    count=len(calls);r2=original(root/'success',d,config,'MOCK','https://api.deepseek.com',transport=fake_for(d),poll_seconds=0)
    assert r2==r and len(calls)==count

    def intent(folder,b):
        runner.jo(folder/'SUBMISSION_INTENT.json',{**b,'protocol':runner.PROTOCOL,'online_start_utc':runner.utc(),
            'post_start_utc':runner.utc(),'base_url':'https://api.openai.com/v1' if b['provider']=='luna' else 'https://api.deepseek.com','preparation_seconds':0.})
    folder=root/'queued/attempts'/l['attempt_id'];intent(folder,l)
    runner.save_http(folder,'POST',{'http_status':200,'mock':True},json.dumps(response(l,queued=True)).encode())
    count=len(calls);resumed=original(root/'queued',l,config,'MOCK','https://api.openai.com/v1',transport=fake_for(l),poll_seconds=0)
    assert calls[count:]==[(l['attempt_id'],'GET')] and resumed['resumed_after_process_interruption'] and resumed['admissible']
    assert resumed['response_id']=='resp_mock_'+str(l['rank'])

    folder=root/'uncertain/attempts'/d['attempt_id'];intent(folder,d);count=len(calls)
    try:original(root/'uncertain',d,config,'MOCK','https://api.deepseek.com',transport=fake_for(d),poll_seconds=0)
    except RuntimeError as e:assert 'no re-POST' in str(e)
    else:raise AssertionError('uncertain intent was not preserved')
    assert len(calls)==count and runner.read(folder/'TERMINAL.json')['submission_state']=='uncertain_delivery'

    folder=root/'retrieval_error/attempts'/l['attempt_id'];intent(folder,l)
    runner.save_http(folder,'POST',{'http_status':200,'mock':True},json.dumps(response(l,queued=True)).encode())
    def rate_error(method,url,key,body=None,timeout=60):
        calls.append((l['attempt_id'],method));return {'http_status':429,'mock':True},b'{"error":{"code":"rate_limit_exceeded"}}'
    count=len(calls)
    try:original(root/'retrieval_error',l,config,'MOCK','https://api.openai.com/v1',transport=rate_error,poll_seconds=0)
    except RuntimeError as e:assert 'GET-only recovery' in str(e)
    else:raise AssertionError('temporary GET rate error did not stop')
    assert not (folder/'TERMINAL.json').exists() and (folder/'RESPONSE_ID.json').exists()
    recovered=original(root/'retrieval_error',l,config,'MOCK','https://api.openai.com/v1',transport=fake_for(l),poll_seconds=0)
    assert recovered['admissible'] and [method for _,method in calls[count:]]==['GET','GET']

    folder=root/'raw_recovery/attempts'/d['attempt_id'];intent(folder,d)
    raw=b'{"error":{"code":"invalid_api_key"}}';meta={'http_status':401,'mock':True}
    runner.save_http(folder,'POST',meta,raw);runner.jo(folder/'PROVIDER_HTTP.json',meta);runner.once(folder/'PROVIDER_RAW.json',raw)
    count=len(calls);rejected=original(root/'raw_recovery',d,config,'MOCK','https://api.deepseek.com',transport=fake_for(d),poll_seconds=0)
    assert len(calls)==count and rejected['http_status']==401 and rejected['submission_state']=='rejected' and not rejected['admissible']

    # A terminal HTTP-200 credit failure is retained; it halts the next wave.
    waves=root/'waves';dispatched=[];wave_calls=[]
    def wave_attempt(runroot,b,conf,key,base):
        dispatched.append(b['attempt_id'])
        def transport(method,url,key,body=None,timeout=60):
            wave_calls.append((b['attempt_id'],method))
            obj=response(b,queued=(b['attempt_id']==l['attempt_id'] and method=='POST'),failed=(b['attempt_id']==l['attempt_id'] and method=='GET'))
            return {'http_status':200,'mock':True},json.dumps(obj).encode()
        return original(runroot,b,conf,key,base,transport=transport,poll_seconds=0)
    with patch.object(runner,'credentials',side_effect=lambda p:('MOCK','https://api.deepseek.com' if p=='deepseek' else 'https://api.openai.com/v1')),patch.object(runner,'attempt',side_effect=wave_attempt):
        code=runner.execute(waves,freeze)
    assert code==2 and set(dispatched)=={b['attempt_id'] for b in bindings[:4]}
    failed=runner.read(waves/'attempts'/l['attempt_id']/'TERMINAL.json')
    assert failed['submission_state']=='accepted' and failed['finish_reason']=='failed' and failed['systemic_provider_error']=='credit_balance_exhausted'
    count=len(wave_calls)
    old=original(waves,l,runner.read(waves/'CONFIG.json'),'MOCK','https://api.openai.com/v1',transport=fake_for(l),poll_seconds=0)
    assert old==failed and len(wave_calls)==count
    assert runner.systemic_error({'http_status':200},{'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}}) is None
    out=dict(status='PASS',real_http_calls=0,credential_reads=0,formal_generation_posts=0,
        artifact_directory=root.relative_to(ROOT).as_posix(),
        checks=['prepared body reconstruction and hashes','independent verification before availability','no repeat POST for completed request',
         'accepted Responses ID resumes by GET only','uncertain POST intent is never repeated','temporary GET rate error preserves accepted ID without terminalizing',
         'response HTTP metadata survives interruption','HTTP-200 terminal credit failure persists and stops next wave','failed terminal is not re-POSTed',
         'per-request output limit is not a systemic account failure'],
        test_mock_task_scope='Three local complete-sortie fixtures derived from archived pilot geometry; excluded from formal instances and denominators')
    (ROOT/'analysis/candidate_driver_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,indent=2))

if __name__=='__main__':
    with (patch('socket.create_connection',side_effect=AssertionError('REAL_NETWORK_FORBIDDEN')),
          patch('socket.socket.connect',side_effect=AssertionError('REAL_NETWORK_FORBIDDEN'))):
        main()
