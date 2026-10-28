"""Rebuild one unrestricted reference without overwriting the stored study."""
import argparse
from study_common import HERE,read,write
from continuous_engine import Engine

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('record_id');p.add_argument('--budget',type=float,default=600);a=p.parse_args()
    task=read(HERE/'networks/tasks'/f'{a.record_id}.json')
    result=Engine(task).solve(all_served=a.record_id[-1] in 'AB',budget=a.budget)
    target=HERE/'rebuild'/f'{a.record_id}.json';write(target,result)
    print(target,'optimal',result['optimal'],'proved_prefix',result['proved_prefix'],'seconds',result['total_seconds'])
