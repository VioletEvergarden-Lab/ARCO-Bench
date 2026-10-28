"""Final reference/candidate records with the frozen new-network backend."""
import argparse
import concurrent.futures
import shutil
from study_common import HERE,read,write
from continuous_engine import Engine,quality
from run_network_study import candidate_job

OUT=HERE/'networks'
def job(path):
    rid=path.stem; task=read(path); refpath=OUT/'references'/path.name
    old=read(refpath)
    if old.get('solver')!='HiGHS 1.15.1':
        result=Engine(task).solve(all_served=rid[-1] in 'AB',budget=600)
        if not result['optimal']: write(OUT/'consolidation_pending'/path.name,result); print('REF PENDING',rid,result['proved_prefix'],flush=True); return
        if not quality(result['objective'],old['objective']): raise RuntimeError((rid,'reference vector differs',old['objective'],result['objective']))
        archive=OUT/'preflight_backend/references'/path.name; archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists(): shutil.copy2(refpath,archive)
        write(refpath,result)
    candidate=OUT/'candidates'/path.name
    if candidate.exists() and read(candidate)['R4']['result'].get('continuous_prefix_tol')!=1e-5:
        archive=OUT/'preflight_backend/candidates'/path.name; archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists(): shutil.move(str(candidate),str(archive))
        else: candidate.unlink()
    row=candidate_job(path)
    print('FINAL',rid,read(refpath)['total_seconds'],row['R4']['full_seconds'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=3);a=p.parse_args()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool: list(pool.map(job,sorted((OUT/'tasks').glob('NET_*.json'))))
    write(OUT/'candidate_results.json',[read(p) for p in sorted((OUT/'candidates').glob('NET_*.json'))])
