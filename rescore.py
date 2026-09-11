"""Single offline entry point; invokes the unmodified archived scorer."""
import argparse, importlib.util, json, socket, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
def no_network(*args,**kwargs):raise RuntimeError('NETWORK_DISABLED_FOR_OFFLINE_RESCORING')
def runtime():
    socket.create_connection=no_network;socket.socket.connect=no_network
    vendor=ROOT/'vendor';scorer=load('archival_scorer',vendor/'scripts/score_integrated_repair_candidate_a_v12_curated_repair_track_v1.py')
    loader=load('archival_loader',vendor/'scripts/integrated_repair_candidate_a_v12_multitemplate_structural_successor_v1.py');_,bridge,mods=loader.load_runtime(vendor,'release_offline')
    return scorer,bridge,mods
def rows(path):return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
def score(responses,rt):
    sc,bridge,mods=rt;out=[];seen=set()
    for row in responses:
        rid=row['record_id']
        if rid in seen or not rid.startswith('CA12_CORE_'):raise ValueError('INVALID_OR_DUPLICATE_RECORD_ID')
        seen.add(rid);p=ROOT/'data/private/evaluator_records'/f'{rid}.json'
        if not p.is_file():raise ValueError('UNKNOWN_RECORD_ID')
        private=json.loads(p.read_text(encoding='utf-8'));r=sc.score_one(rid,row.get('raw_text',''),private,mods['core'],mods['formal'],bridge,mods)
        r['online_admissible']=bool(r['schema_valid'] and r['formal_feasible']);r['reference_quality']=bool(r['online_admissible'] and r['oracle_equivalent']);r['construct_fidelity']=r['required_repair_semantics'];out.append(r)
    return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--responses',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();result=score(rows(a.responses),runtime());a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'SCORED_RECORDS.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in result),encoding='utf-8')
    summary={k:sum(bool(r[k]) for r in result) for k in ('schema_valid','online_admissible','reference_quality','construct_fidelity','strict_success')};summary.update(records=len(result),network='disabled');(a.output/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary))
if __name__=='__main__':main()
