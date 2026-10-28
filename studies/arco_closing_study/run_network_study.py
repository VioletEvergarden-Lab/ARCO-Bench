"""Bounded generation, exact references, G/R4 and prespecified window pairs."""
import argparse
import concurrent.futures
import copy
import time
from study_common import HERE,read,write,jsonl,csvout
from continuous_engine import Engine,quality
from generate_networks import CONFIG,construct,solo

OUT=HERE/'networks'

def network_job(cell):
    scale,index,base_seed=cell; nid=f'NET_{scale}{index:02d}'; done=OUT/'accepted'/f'{nid}.json'
    if done.exists(): return read(done)
    rejection_path=OUT/'generation_attempts'/nid/'rejections.json'
    attempts=read(rejection_path) if rejection_path.exists() else []
    for attempt in range(len(attempts),CONFIG['attempts_per_network']):
        seed=base_seed+100*attempt
        try:
            states,meta=construct(scale,seed,index)
            references={}; individual=[]
            for uid in Engine(states['C']).fleet:
                witness=Engine(solo(states['C'],uid)).solve(all_served=True,budget=120,stages=1)
                if witness['decisions'] is None: raise ValueError('C individual chain cannot serve '+uid)
                individual.append({'uav_id':uid,'result':witness})
            for condition in 'ABC':
                task=states[condition]; eng=Engine(task)
                if eng.verify(task['baseline']['decisions'])['admissible']: raise ValueError('intervention does not require incumbent repair')
                ref_path=OUT/'generation_attempts'/nid/f'{attempt:02d}_{condition}_reference.json'
                reference=read(ref_path) if ref_path.exists() else eng.solve(all_served=condition in 'AB',budget=CONFIG['reference_total_budget_seconds']); references[condition]=reference
                if not ref_path.exists(): write(ref_path,reference)
                print(task['record_id'],'attempt',attempt,'reference',reference['optimal'],'prefix',reference['proved_prefix'],'seconds',round(reference['total_seconds'],1),flush=True)
                if not reference['optimal']:
                    status=reference['phases'][-1]['status'] if reference['phases'] else None
                    raise ValueError((condition+' all-service infeasible') if condition in 'AB' and status==2 else ('reference stage '+condition+' status '+str(status)+' prefix '+str(reference['proved_prefix'])))
                if condition in 'AB' and reference['objective']['total_holds']!=0: raise ValueError(condition+' cannot restore all service')
                if condition=='C' and reference['objective']['total_holds']==0: raise ValueError('C joint all service remains possible')
            meta.update(base_seed=base_seed,attempt=attempt,rejected_attempts=attempts,individual_C_all_service=True)
            for condition in 'ABC':
                task=states[condition]; rid=task['record_id']; write(OUT/'tasks'/f'{rid}.json',task); write(OUT/'references'/f'{rid}.json',references[condition])
            write(OUT/'individual_C'/f'{nid}.json',individual); write(done,meta); print(nid,'ACCEPTED',flush=True); return meta
        except ValueError as exc:
            attempts.append({'attempt':attempt,'seed':seed,'reason':str(exc)}); write(OUT/'generation_attempts'/nid/'rejections.json',attempts); print(nid,'reject',attempt,str(exc),flush=True)
    write(OUT/'unfilled'/f'{nid}.json',{'network_id':nid,'attempts':attempts})
    return {'network_id':nid,'unfilled':True,'attempts':attempts}

def candidate_job(path):
    rid=path.stem; target=OUT/'candidates'/f'{rid}.json'
    if target.exists(): return read(target)
    start=time.perf_counter(); task=read(path); eng=Engine(task)
    g=eng.greedy(); gs=eng.verify(g); gt=time.perf_counter()-start
    result=eng.solve(g,4,budget=600); rs=eng.verify(result['decisions']) if result['decisions'] else None
    full_seconds=time.perf_counter()-start; ref=read(OUT/'references'/path.name)
    row={'record_id':rid,'network_id':rid[:-2],'scale':rid.split('_')[1][0],'condition':rid[-1],'G':{'decisions':g,'score':gs,'quality':gs['admissible'] and quality(gs['objective'],ref['objective']),'total_seconds':gt},'R4':{'result':result,'score':rs,'quality':bool(rs and rs['admissible'] and quality(rs['objective'],ref['objective'])),'full_seconds':full_seconds}}
    write(target,row); print(rid,'G/R4',row['G']['quality'],row['R4']['quality'],'seconds',round(gt,2),round(result['total_seconds'],2),flush=True); return row

def sensitivity_job(rid):
    folder=HERE/'window_sensitivity'; target=folder/'results'/f'{rid}.json'
    if target.exists(): return read(target)
    task=read(OUT/'tasks'/f'{rid}.json'); task['timing']['pad_window_min']=task['timing']['resource_window_min']; task['timing']['resource_window_min']=0.5
    eng=Engine(task); ref=eng.solve(all_served=rid[-1]=='B',budget=600); g=eng.greedy(); local=eng.solve(g,4,budget=600)
    gs=eng.verify(g); rs=eng.verify(local['decisions']) if local['decisions'] else None
    row={'record_id':rid,'window_min':0.5,'reference':ref,'G':{'decisions':g,'score':gs},'R4':{'result':local,'score':rs}}
    write(folder/'tasks'/f'{rid}.json',task); write(target,row); print('WINDOW_HALF',rid,'reference',ref['optimal'],'prefix',ref['proved_prefix'],flush=True); return row

def run(mode,workers,available=False):
    if mode=='generate':
        write(OUT/'generation_config.json',CONFIG)
        cells=[(s,i,seed) for s,seeds in CONFIG['formal_seeds'].items() for i,seed in enumerate(seeds,1)]
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool: results=list(pool.map(network_job,cells))
        write(OUT/'accepted_networks.json',results)
    elif mode=='candidates':
        paths=sorted((OUT/'tasks').glob('NET_*.json'))
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool: results=list(pool.map(candidate_job,paths))
        write(OUT/'candidate_results.json',results)
    elif mode=='sensitivity':
        ids=[f'NET_{s}01_{c}' for s in 'SML' for c in 'BC']; write(HERE/'window_sensitivity/config.json',{'task_ids':ids,'corridor_charger_windows_min':[1,0.5],'pad_movement_window_min':1,'unchanged':'geometry, departure grid, actual events, power, releases, baseline, interventions and pad throughput unit','model_regenerations':0})
        ready=[rid for rid in ids if (OUT/'tasks'/f'{rid}.json').exists()] if available else ids
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool: results=list(pool.map(sensitivity_job,ready))
        write(HERE/'window_sensitivity/results.json',results)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['generate','candidates','sensitivity']); p.add_argument('--workers',type=int,default=3); p.add_argument('--available',action='store_true'); args=p.parse_args(); run(args.mode,args.workers,args.available)
