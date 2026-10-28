"""One complete R3 pass and four post-generation selector timing passes."""
import os
import re
import subprocess
from common import *

def main():
    banner=subprocess.run([sys.executable,'-c',"import numpy as np; from scipy.optimize import milp,Bounds; milp(np.array([1.]),integrality=np.ones(1),bounds=Bounds([0],[1]),options={'disp':True})"],capture_output=True,text=True,check=True).stdout
    version=re.search(r'Running HiGHS ([^ ]+)',banner).group(1)
    rt=Runtime(); seeds=decisions(R/'policy_domains/public_both.jsonl'); rows=[]
    for path in sorted((P/'data/public/records').glob('CA12_CORE_*.json')):
        t0=time.perf_counter(); task=read(path); t1=time.perf_counter(); g=rt.greedy(task); t2=time.perf_counter()
        if diff(g,seeds[task['record_id']]): raise RuntimeError(('G adapter changed',task['record_id']))
        sol,build_sec=local_repair(rt,task,g); t3=time.perf_counter(); score=rt.evaluate(task,sol['decisions']); t4=time.perf_counter()
        if not score['formal_feasible']: raise RuntimeError(score)
        rows.append({'record_id':task['record_id'],'load_sec':t1-t0,'greedy_sec':t2-t1,'neighborhood_build_sec':build_sec,'lex_solve_sec':sum(sol['phase_seconds'].values()),'verification_sec':t4-t3,'total_sec':t4-t0,'phase_seconds':sol['phase_seconds'],'decisions':sol['decisions'],'objective':score['objective_vector']})
    sources={'G':{r['record_id']:r['raw_text'] for r in jl(R/'policy_domains/public_both.jsonl')},'R3':{r['record_id']:r['raw_text'] for r in jl(R/'local_repair/responses.jsonl')}}
    models={name:{r['record_id']:r.get('raw_text','') for r in jl(P/f'responses/{name}_complete.jsonl')} for name in ('deepseek','luna')}
    selector_rows=[]
    for local,plans in sources.items():
        for model,answers in models.items():
            for rid,raw in sorted(plans.items()):
                task=read(P/'data/public/records'/f'{rid}.json'); start=time.perf_counter()
                parsed_a,err_a=rt.selector.parse_public(raw,task); parsed_b,err_b=rt.selector.parse_public(answers[rid],task)
                a=rt.selector.public_evaluate(parsed_a,err_a,task,rt.formal); b=rt.selector.public_evaluate(parsed_b,err_b,task,rt.formal)
                chosen='local' if a['formal_feasible'] and (not b['formal_feasible'] or rt.selector.lex_compare(a['objective_vector'],b['objective_vector'])<=0) else 'model' if b['formal_feasible'] else 'none'
                selector_rows.append({'record_id':rid,'pair':local+'+'+model,'seconds':time.perf_counter()-start,'chosen':chosen})
    def stats(values): return {'mean_sec':statistics.mean(values),'median_sec':statistics.median(values),'p95_sec':float(np.quantile(values,.95))}
    env={'os':platform.platform(),'cpu':platform.processor(),'python':sys.version,'scipy':scipy.__version__,'numpy':np.__version__,'logical_processors':os.cpu_count(),'threads':'HiGHS default; no override','highs_version':version}
    if os.name=='nt':
        import winreg
        env['cpu']=winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'),'ProcessorNameString')[0].strip()
    summary={'environment':env,'R3':{name:stats([r[name] for r in rows]) for name in ('total_sec','load_sec','greedy_sec','neighborhood_build_sec','lex_solve_sec','verification_sec')},'selector':{pair:stats([r['seconds'] for r in selector_rows if r['pair']==pair]) for pair in sorted({r['pair'] for r in selector_rows})}}
    out=HERE/'timing'; write(out/'end_to_end.json',{'summary':summary,'tasks':rows}); csvout(out/'selector_times.csv',selector_rows); write(out/'summary.json',summary)
    (out/'highs_version.txt').write_text(banner,encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
