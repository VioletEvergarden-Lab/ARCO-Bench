"""Mock transport checks only: never reads credentials or sends HTTP requests."""
import json
import time
from pathlib import Path
from unittest.mock import patch
import run_new_models as runner
from run_new_models import ROOT,PREPARED,read,rebuild_request,attempt,jo,save_http,utc,PROTOCOL
from optimization_online import Engine


def main():
    bindings=read(PREPARED/'BINDINGS.json')
    d=next(b for b in bindings if b['provider']=='deepseek')
    l=next(b for b in bindings if b['provider']=='luna' and b['record_id']==d['record_id'])
    task,_=rebuild_request(d)
    plan=Engine(task).greedy()
    content=json.dumps({'record_id':task['record_id'],'decisions':plan})
    deepseek={'model':'deepseek-v4-pro','id':'mock_deepseek',
              'choices':[{'finish_reason':'stop','message':{'content':content}}]}
    luna={'model':'gpt-5.6-luna','id':'resp_mock','status':'completed',
          'output':[{'type':'message','content':[{'type':'output_text','text':content}]}]}
    testroot=ROOT/'results/generation/mock_transport_checks'/str(time.time_ns())
    calls=[]
    def fake(method,url,key,body=None,timeout=60):
        calls.append(method)
        response=deepseek if 'chat/completions' in url else luna
        return {'http_status':200,'started_utc':utc(),'ended_utc':utc(),'elapsed_seconds':0.,'mock':True},json.dumps(response).encode()
    r=attempt(testroot,d,'MOCK_NOT_A_CREDENTIAL','https://api.deepseek.com',transport=fake,poll_seconds=0)
    assert r['admissible'] and r['available_seconds']>=r['response_seconds']
    count=len(calls)
    again=attempt(testroot,d,'MOCK_NOT_A_CREDENTIAL','https://api.deepseek.com',transport=fake,poll_seconds=0)
    assert len(calls)==count and again['objective']==r['objective']
    # Simulate an interrupted Luna request with a durable response ID. Only a
    # GET may be sent when the saved queued response is recovered.
    folder=testroot/'attempts'/l['attempt_id']
    intent={**l,'protocol':PROTOCOL,'online_start_utc':utc(),'post_start_utc':utc(),
            'base_url':'https://api.openai.com/v1','preparation_seconds':0.}
    jo(folder/'SUBMISSION_INTENT.json',intent)
    save_http(folder,'POST',{'http_status':200,'mock':True},json.dumps({'id':'resp_mock','status':'queued'}).encode())
    count=len(calls)
    resumed=attempt(testroot,l,'MOCK_NOT_A_CREDENTIAL','https://api.openai.com/v1',transport=fake,poll_seconds=0)
    assert calls[count:]==['GET'] and resumed['admissible'] and resumed['resumed_after_process_interruption']
    uncertain=next(b for b in bindings if b['provider']=='deepseek' and b['attempt_id']!=d['attempt_id'])
    folder=testroot/'attempts'/uncertain['attempt_id']
    jo(folder/'SUBMISSION_INTENT.json',{**uncertain,'protocol':PROTOCOL,'online_start_utc':utc(),
       'post_start_utc':utc(),'base_url':'https://api.deepseek.com','preparation_seconds':0.})
    count=len(calls)
    try:
        attempt(testroot,uncertain,'MOCK_NOT_A_CREDENTIAL','https://api.deepseek.com',transport=fake,poll_seconds=0)
        raise AssertionError('uncertain intent did not stop')
    except RuntimeError as exc:
        assert 'no re-POST' in str(exc)
    assert len(calls)==count
    # A Responses API account error may be HTTP 200 + status=failed. It must
    # save the terminal, finish the current four-request wave, then stop.
    wave_root=testroot/'systemic_wave'
    wave_bindings=bindings[:8]
    failing=next(b for b in wave_bindings[:4] if b['provider']=='luna')
    dispatched=[]; wave_calls=[]
    original_attempt=runner.attempt
    def fake_prepare(root):
        root.mkdir(parents=True,exist_ok=True)
        return {},wave_bindings
    def wave_attempt(root,binding,key,base):
        dispatched.append(binding['attempt_id'])
        def wave_transport(method,url,key,body=None,timeout=60):
            wave_calls.append((binding['attempt_id'],method))
            if binding['provider']=='luna':
                response={'model':'gpt-5.6-luna','id':'resp_mock_'+str(binding['rank']),
                          'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}
                if binding['attempt_id']==failing['attempt_id']:
                    response['status']='queued' if method=='POST' else 'failed'
                    if method=='GET':
                        response['error']={'code':'credit_balance_exhausted','message':'Credit balance exhausted'}
                    response.pop('incomplete_details')
            else:
                response={'model':'deepseek-v4-pro','choices':[{'finish_reason':'length','message':{'content':''}}]}
            return {'http_status':200,'mock':True},json.dumps(response).encode()
        return original_attempt(root,binding,key,base,transport=wave_transport,poll_seconds=0)
    with patch.object(runner,'prepare',side_effect=fake_prepare), \
         patch.object(runner,'credentials',side_effect=lambda provider:('MOCK_NOT_A_CREDENTIAL','https://mock.invalid')), \
         patch.object(runner,'attempt',side_effect=wave_attempt):
        exit_code=runner.execute(wave_root)
    assert exit_code==2
    assert set(dispatched)=={b['attempt_id'] for b in wave_bindings[:4]}
    assert sum(method=='POST' for _,method in wave_calls)==4
    assert [method for aid,method in wave_calls if aid==failing['attempt_id']]==['POST','GET']
    assert len(wave_calls)==5
    failed_folder=wave_root/'attempts'/failing['attempt_id']
    stored=read(failed_folder/'TERMINAL.json')
    assert stored['http_status']==200 and stored['finish_reason']=='failed'
    assert stored['error']['code']=='credit_balance_exhausted' and stored['systemic_provider_error']=='credit_balance_exhausted'
    assert (failed_folder/'PROVIDER_RAW.json').exists() and (failed_folder/'POST_RAW.bin').exists()
    def forbidden_transport(*args,**kwargs):
        raise AssertionError('a completed failed attempt must not POST again')
    repeated=original_attempt(wave_root,failing,'MOCK_NOT_A_CREDENTIAL','https://mock.invalid',transport=forbidden_transport)
    assert repeated==stored
    for code in ('insufficient_quota','rate_limit_exceeded','quota_exceeded','billing_hard_limit_reached'):
        assert runner.systemic_provider_error({'http_status':200},{'status':'failed','error':{'code':code}})==code
    assert runner.systemic_provider_error({'http_status':429},{})=='http_429'
    assert runner.systemic_provider_error({'http_status':200},{'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}}) is None
    assert runner.systemic_provider_error({'http_status':200},{'status':'failed','error':{'code':'max_output_tokens','message':'Output token limit reached'}}) is None
    result={'passed':True,'real_http_calls':0,'mock_calls':calls,
            'checks':['full response independently verified before delivery',
                      'completed attempt idempotent without POST',
                      'saved response ID resumed with GET only',
                      'uncertain POST intent not repeated',
                      'queued POST then HTTP 200 credit-failed GET persists terminal and raw response before stopping',
                      'systemic failure stops before next wave and completed failed attempt is not re-POSTed',
                      'quota/rate errors stop; per-request max_output_tokens does not'],
            'systemic_wave_exit_code':exit_code,'systemic_wave_dispatched':dispatched,'systemic_wave_mock_calls':wave_calls,
            'mock_artifact_directory':str(testroot.relative_to(ROOT))}
    (ROOT/'results/generation/runner_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    with patch('socket.create_connection',side_effect=AssertionError('NETWORK_FORBIDDEN_IN_MOCK_CHECK')), \
         patch('socket.socket.connect',side_effect=AssertionError('NETWORK_FORBIDDEN_IN_MOCK_CHECK')):
        main()
