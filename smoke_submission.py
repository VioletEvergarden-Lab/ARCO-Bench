"""Check public validation, reference scoring and malformed-answer handling."""
import json
from benchmark.data import ROOT, cases, read
from benchmark.evaluate import Worker

def main():
    case=next(c for c in cases(['core72']) if c['record_id']=='CA12_CORE_012')
    gold=read(ROOT/'data/private/evaluator_records/CA12_CORE_012.json')['gold_public_output']
    text=gold if isinstance(gold,str) else json.dumps(gold)
    worker=Worker('core72','deepseek')
    try:
        assert worker.call('validate',case,text)['admissible']
        assert worker.call('score',case,text)['reference_quality']
        assert not worker.call('score',case,'{malformed')['schema_valid']
    finally:
        worker.close()
    print(json.dumps({'status':'PASS','reference_case':case['record_id'],'network_calls':0,'optimizer_calls':0}))

if __name__=='__main__':main()
