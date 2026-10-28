"""Provider-neutral offline request preparation. Never imports a network client."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--interface',choices=['chat_completions','responses'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('Choose a new output directory; existing requests are preserved.')
    a.output.mkdir(parents=True)
    system=(ROOT/'prompts/system.txt').read_text(encoding='utf-8').strip();instructions=(ROOT/'prompts/complete_public_instructions.md').read_text(encoding='utf-8')
    for path in sorted((ROOT/'data/public/records').glob('*.json')):
        task=json.loads(path.read_text(encoding='utf-8'));user=instructions+'\n\nPublic task:\n\n'+json.dumps(task,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        messages=[{'role':'system','content':system},{'role':'user','content':user}]
        body={'model':a.model,'messages':messages,'max_tokens':128000,'temperature':0} if a.interface=='chat_completions' else {'model':a.model,'input':[{'role':'user','content':user}],'max_output_tokens':128000,'reasoning':{'effort':'max','mode':'standard','context':'current_turn'},'background':True,'store':False,'stream':False,'tools':[]}
        (a.output/(path.stem+'.json')).write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (a.output/'PREPARATION_ONLY.json').write_text(json.dumps({'instruction_condition':'complete_public_rules_20260922','model':a.model,'interface':a.interface,'count':72,'online_calls':0,'status':'prepared_not_executed','note':'Historical field templates; endpoint support and identity require confirmation before a separately authorized run.'},indent=2)+'\n',encoding='utf-8')
    print('Prepared 72 requests; zero network calls.')
if __name__=='__main__':main()
