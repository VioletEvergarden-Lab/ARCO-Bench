"""One actual Core-72 R4 pass using only public tasks and freshly generated G."""
import json
import time
import statistics
import numpy as np
from study_common import *

def main():
    out=HERE/'core_r4'; out.mkdir(exist_ok=True)
    runtime=Runtime(); rows=[]; answers=[]
    for path in sorted((P/'data/public/records').glob('CA12_CORE_*.json')):
        start=time.perf_counter(); task=read(path); loaded=time.perf_counter()
        g=runtime.greedy(task); seeded=time.perf_counter()
        solved,build_seconds=local_repair(runtime,task,g,k=4); optimized=time.perf_counter()
        score=runtime.evaluate(task,solved['decisions']); end=time.perf_counter()
        if not score['formal_feasible']: raise RuntimeError((task['record_id'],score))
        rows.append({'record_id':task['record_id'],'decisions':solved['decisions'],'objective':score['objective_vector'],'admissible':True,'changed_missions':diff(g,solved['decisions']),'load_seconds':loaded-start,'G_seconds':seeded-loaded,'build_seconds':build_seconds,'solve_seconds':sum(solved['phase_seconds'].values()),'verify_seconds':end-optimized,'total_seconds':end-start,'phases':solved['phase_seconds']})
        answers.append({'record_id':task['record_id'],'raw_text':json.dumps({'record_id':task['record_id'],'decisions':solved['decisions']})})
        if len(rows)%12==0: print('Core R4',len(rows),'/72',flush=True)
    # Reference vectors enter only the evaluation following candidate generation.
    from common import quality
    refs={r['record_id']:r['objective'] for r in jl(P/'references/public_domain.jsonl')}
    for row in rows: row['reference_quality']=quality(row['objective'],refs[row['record_id']])
    pairs=[]
    for model in ('deepseek','luna'):
        responses={r['record_id']:r['raw_text'] for r in jl(P/f'responses/{model}_complete.jsonl')}
        for row in rows:
            task=read(P/'data/public/records'/f"{row['record_id']}.json")
            parsed,errors=runtime.selector.parse_public(responses[row['record_id']],task)
            score=runtime.selector.public_evaluate(parsed,errors,task,runtime.formal)
            choose_local=not score['formal_feasible'] or runtime.selector.lex_compare(row['objective'],score['objective_vector'])<=0
            selected=row['objective'] if choose_local else score['objective_vector']
            pairs.append({'record_id':row['record_id'],'pair':'R4+'+model,'selected':'R4' if choose_local else model,'selected_quality':quality(selected,refs[row['record_id']]),'model_quality':bool(score['formal_feasible'] and quality(score['objective_vector'],refs[row['record_id']]))})
    times=[r['total_seconds'] for r in rows]
    summary={'tasks':len(rows),'R4_admissible':sum(r['admissible'] for r in rows),'R4_quality':sum(r['reference_quality'] for r in rows),'R4_served':sum(not d['held'] for r in rows for d in r['decisions']),'total_time_seconds':{'mean':statistics.mean(times),'median':statistics.median(times),'p95':float(np.quantile(times,.95))},'pairs':{p:{'selected_quality':sum(r['selected_quality'] for r in pairs if r['pair']==p),'selected_R4':sum(r['selected']=='R4' for r in pairs if r['pair']==p)} for p in ('R4+deepseek','R4+luna')}}
    write(out/'results.json',rows); jsonl(out/'responses.jsonl',answers); csvout(out/'per_task.csv',rows); csvout(out/'selection.csv',pairs); write(out/'summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__': main()
