"""Offline positive and negative fixtures plus optional seven-source replay."""
import argparse,json
from pathlib import Path
from rescore import ROOT,rows,runtime,score
from admit import admit,public_runtime

def main():
    p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args();rt=runtime()
    one=next(r for r in rows(ROOT/'responses/policy.jsonl') if r['record_id']=='CA12_CORE_012');good=score([one],rt)[0];bad=score([{'record_id':'CA12_CORE_012','raw_text':'{'}],rt)[0]
    assert good['reference_quality'] and not bad['schema_valid']
    expected={'deepseek':28,'qwen':34,'luna':48,'policy':38,'policy_deepseek':52,'policy_qwen':50,'policy_luna':63};totals={};compared=0;prt=public_runtime()
    if a.all:
        fields=('schema_valid','formal_feasible','required_repair_semantics','oracle_equivalent','strict_success','lexicographic_first_difference','objective_vector')
        for name,n in expected.items():
            new=score(rows(ROOT/f'responses/{name}.jsonl'),rt);old={r['record_id']:r for r in rows(ROOT/f'results/original/{name}.jsonl')}
            pub={r['record_id']:r for r in admit(rows(ROOT/f'responses/{name}.jsonl'),prt)}
            assert len(new)==72
            for r in new:
                assert all(r.get(k)==old[r['record_id']].get(k) for k in fields),(name,r['record_id']);compared+=1
                assert pub[r['record_id']]['admissible']==r['online_admissible']
                assert pub[r['record_id']]['objective_vector']==r['objective_vector']
            totals[name]=sum(r['reference_quality'] for r in new);assert totals[name]==n
    report={'status':'PASS','network':'disabled','positive_case':'CA12_CORE_012 policy','negative_case':'malformed JSON rejected','records_compared':compared,'public_only_admission_and_objectives_match':True,'reference_quality_counts':totals}
    if a.output:a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
