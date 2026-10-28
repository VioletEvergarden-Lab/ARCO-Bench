"""Use final continuous G/R4 while retaining completed semantic references."""
from study_common import HERE,read,write,jl,jsonl,csvout
from continuous_engine import Engine,quality

def main():
    folder=HERE/'semantic_bridge'; rows=read(folder/'results.json'); plans=jl(folder/'plans.jsonl'); retained=[p for p in plans if p['source'] not in ['G','R4']]; events=[dict(e,source=p['source']) for p in retained if p.get('score') for e in p['score'].get('events',[])]
    for row in rows:
        rid=row['record_id']; task=read(folder/'tasks'/f'{rid}.json'); eng=Engine(task); g=eng.greedy(); r=eng.solve(g,4,budget=180); reference=read(folder/'references'/f'{rid}.json')
        for source,ds in [('G',g),('R4',r['decisions'])]:
            score=eng.verify(ds); row[source+'_quality']=score['admissible'] and quality(score['objective'],reference['objective']); retained.append({'record_id':rid,'source':source,'decisions':ds,'score':score}); events.extend(dict(e,source=source) for e in score['events'])
        print(rid,row['G_quality'],row['R4_quality'],flush=True)
    write(folder/'results.json',rows); csvout(folder/'results.csv',rows); jsonl(folder/'plans.jsonl',retained); csvout(folder/'events.csv',events)

if __name__=='__main__': main()
