"""Run the 36 preference references and at most six prespecified restrictions."""
import argparse, json
from pathlib import Path
from preference_solver import ROOT, OLD, solve

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--ids',nargs='*'); p.add_argument('--budget',type=float,default=600); p.add_argument('--restrictions',action='store_true'); a=p.parse_args()
    if a.restrictions:
        records=read(ROOT/'protocol/preference_restriction_selection.json')['selected']
        jobs=[(r['record_id'],mode) for r in records for mode in ('fixed_route','fixed_charge')]
    else:
        ids=a.ids or [f'NET_{s}{i:02d}_{c}' for s in 'SML' for i in range(1,5) for c in 'ABC']
        jobs=[(rid,None) for rid in ids]
    for rid,mode in jobs:
        if (ROOT/'protocol/PAUSE_HEAVY_COMPUTE').exists():
            print('PAUSED before',rid,mode,flush=True); return
        target=ROOT/'results/preference'/('restrictions' if mode else 'references')/(rid+(('_'+mode) if mode else '')+'.json')
        if target.exists(): continue
        task=read(OLD/'networks/tasks'/f'{rid}.json'); original=read(OLD/'networks/references'/f'{rid}.json')
        base={d['mission_id']:d for d in task['baseline']['decisions']}
        allowed=(lambda o: o['path_id']==base[o['mission_id']]['path_id']) if mode=='fixed_route' else (lambda o:o['charge_blocks']==base[o['mission_id']]['charge_blocks']) if mode=='fixed_charge' else None
        warm=read(ROOT/'results/preference/references'/f'{rid}.json')['decisions'] if mode else original['decisions']
        service=[original['objective']['urgent_holds'],original['objective']['total_holds']] if mode else None
        print('START',rid,mode or 'preference',flush=True)
        result=solve(task,budget=a.budget,warm=warm,allowed=allowed,service=service)
        result.update(restriction=mode,original_reference_optimal=original['optimal'])
        write(target,result)
        print('DONE',rid,mode or 'preference',result['status'],result['proved_prefix'],round(result['total_seconds'],2),result['objective'],flush=True)

if __name__=='__main__': main()
