"""Offline public/reference scoring fixtures and input-template checks."""
import json,platform,sys
import numpy,scipy
from rescore import ROOT,rows,score,runtime
from admit import admit,public_runtime

def main():
    sample=next(x for x in rows(ROOT/'responses/reference.jsonl') if x['record_id']=='CA12_CORE_012')
    bad={'record_id':'CA12_CORE_012','raw_text':'{malformed'}
    rt=runtime();p=public_runtime()
    goodscore=score([sample],rt)[0];badscore=score([bad],rt)[0]
    goodpublic=admit([sample],p)[0];badpublic=admit([bad],p)[0]
    assert goodscore['reference_quality'] and goodpublic['admissible']
    assert not badscore['schema_valid'] and not badpublic['admissible']
    instructions=(ROOT/'prompts/complete_public_instructions.md').read_text(encoding='utf-8')
    assert all(t in instructions for t in ('0.06','0.05','horizon_slots','1000 * L2','20*','10*','2*','w=10','duration_slots','reserve_kwh'))
    print(json.dumps({'status':'PASS','reference_case':'CA12_CORE_012','malformed_answer_rejected':True,'public_reference_agreement':True,'template_rule_checks':True,'network':'disabled','python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__,'executable':sys.executable},indent=2))
if __name__=='__main__':main()
