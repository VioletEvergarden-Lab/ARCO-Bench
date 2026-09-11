"""Public-state-only admission and objective computation; never loads references."""
import argparse,json
from pathlib import Path
from rescore import ROOT,load,rows,no_network
import socket

def public_runtime():
    socket.create_connection=no_network;socket.socket.connect=no_network
    selector=load('public_selector',ROOT/'vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py')
    formal=load('public_formal',ROOT/'vendor/scripts/validate_integrated_repair_phase_minus1d_v1.py')
    return selector,formal
def admit(responses,rt):
    selector,formal=rt;out=[];seen=set()
    for r in responses:
        rid=r['record_id']
        if rid in seen or not rid.startswith('CA12_CORE_'):raise ValueError('INVALID_OR_DUPLICATE_RECORD_ID')
        seen.add(rid);task=json.loads((ROOT/f'data/public/records/{rid}.json').read_text(encoding='utf-8'))
        parsed,errors=selector.parse_public(r.get('raw_text',''),task);v=selector.public_evaluate(parsed,errors,task,formal)
        out.append({'record_id':rid,**v,'admissible':bool(v['schema_valid'] and v['formal_feasible'])})
    return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--responses',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();result=admit(rows(a.responses),public_runtime());a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in result),encoding='utf-8');print(json.dumps({'records':len(result),'admissible':sum(r['admissible'] for r in result),'reference_access':False,'network':'disabled'}))
if __name__=='__main__':main()
