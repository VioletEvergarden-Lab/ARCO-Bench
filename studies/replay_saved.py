"""Replay saved study evidence with networking and optimization disabled."""
from pathlib import Path
import argparse, collections, contextlib, hashlib, importlib, io, json, runpy, socket, subprocess, sys

STUDIES=Path(__file__).resolve().parent
REPO=STUDIES.parent
GROUPS=('networks','sensitivity','core_diagnostics','scope','candidate_diagnostics','origin_target','capacity','adds')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def deny(*args,**kwargs):
    raise RuntimeError('This command only replays saved evidence; network and optimizer calls are disabled.')

def guard():
    sys.dont_write_bytecode=True
    socket.create_connection=deny;socket.socket.connect=deny;socket.socket.connect_ex=deny
    import highspy
    import scipy.optimize
    highspy.Highs.run=deny
    scipy.optimize.milp=deny

def module(folder,name):
    sys.path.insert(0,str(STUDIES/folder))
    return importlib.import_module(name)

def network_check():
    m=module('arco_contribution_20261011/scripts','coordination_study')
    from continuous_engine import Engine,parse,quality,compare
    cases=m.load_cases();assert len(cases)==60
    counts=collections.Counter();quality_counts=collections.Counter()
    old=STUDIES/'arco_closing_study';new=STUDIES/'arco_focused_revision_20261002'
    bindings={(b['record_id'],b['provider']):b for b in read(old/'online/BINDINGS.json')}
    for c in cases:
        rid=c['record_id'];task=c['task'];engine=Engine(task);ref=c['reference']
        verified=engine.verify(ref['decisions']);assert verified['admissible']
        assert quality(verified['objective'],ref['objective'])
        counts['reference_plans']+=1
        for method in m.METHODS:
            saved=c['candidates'][method];ds=saved['decisions']
            score=engine.verify(ds);assert score['admissible']==saved['admissible']
            if score['admissible']:
                assert compare(score['objective'],saved['objective'])==0
                quality_counts[c['group']+':'+method]+=quality(score['objective'],ref['objective'])
            counts['deterministic_plans']+=1
            for event in saved['run'].get('improvements',[]):
                v=engine.verify(event['decisions']);assert v['admissible'] and compare(v['objective'],event['objective'])==0
                counts['deterministic_improvement_plans']+=1
        for provider in ('deepseek','luna'):
            if c['group']=='original':
                attempt=old/'online'/provider/'attempts'/rid
                terminal=read(attempt/'TERMINAL.json')
                public_id=bindings[rid,provider]['public_record_id']
            else:
                attempt=new/'online/new_generation/attempts'/f'{rid}__{provider}__r1'
                terminal=read(attempt/'TERMINAL.json')
                public_id=terminal.get('public_record_id')
                if not public_id:
                    b=next(b for b in read(new/'online/new_generation/BINDINGS.json') if b['attempt_id']==f'{rid}__{provider}__r1')
                    public_id=b['public_record_id']
            counts['scheduled_first_terminal_records']+=1
            stored=c['candidates'][provider]
            if not terminal.get('usable_text'):
                assert not stored['admissible'];counts['first_model_no_usable_text']+=1;continue
            public_task=dict(task,record_id=public_id)
            decisions,errors=parse(terminal['raw_text'],public_task)
            if errors:
                assert not stored['admissible'];counts['first_model_schema_invalid']+=1;continue
            score=Engine(public_task).verify(decisions)
            assert score['admissible']==stored['admissible']
            if score['admissible']:
                assert compare(score['objective'],stored['objective'])==0
                quality_counts[c['group']+':'+provider]+=quality(score['objective'],ref['objective'])
            counts['first_model_plans']+=1
    assert counts['reference_plans']==60 and counts['deterministic_plans']==300 and counts['scheduled_first_terminal_records']==120
    runner=module('arco_focused_revision_20261002/scripts','run_new_models')
    for b in read(new/'online/new_generation/BINDINGS.json'):
        if b['repeat']==1:continue
        terminal=read(new/'online/new_generation/attempts'/b['attempt_id']/'TERMINAL.json')
        counts['repeat_model_terminals']+=1
        if not terminal.get('usable_text'):continue
        task,_=runner.rebuild_request(b);decisions,errors=parse(terminal['raw_text'],task)
        if errors:assert not terminal['admissible'];continue
        v=Engine(task).verify(decisions);assert v['admissible']==terminal['admissible']
        if v['admissible']:assert compare(v['objective'],terminal['objective'])==0
        counts['repeat_model_plans']+=1
    assert counts['repeat_model_terminals']==48
    return {'status':'PASS','coverage':dict(counts),'reference_quality':dict(quality_counts)}

def sensitivity_check():
    ce=module('arco_closing_study','continuous_engine')
    old=STUDIES/'arco_closing_study';focus=STUDIES/'arco_focused_revision_20261002'
    counts=collections.Counter()
    for folder in ('references','restrictions'):
        for p in (focus/'results/preference'/folder).glob('*.json'):
            q=read(p);task=read(old/'networks/tasks'/(q['record_id']+'.json'))
            counts['preference_'+folder]+=1
            if q['decisions'] is None:
                assert folder=='restrictions' and q['status']=='infeasible'
                assert any(p['status']==2 for p in q['phases'])
                counts['preference_restriction_infeasible_records']+=1;continue
            assert q['optimal'] and q['proved_prefix']==6
            v=ce.Engine(task).verify(q['decisions']);assert v['admissible'] and ce.compare(v['objective'],q['objective'])==0
    assert counts['preference_references']==36 and counts['preference_restrictions']==12
    for p in (old/'window_sensitivity/results').glob('*.json'):
        q=read(p);task=read(old/'window_sensitivity/tasks'/p.name);engine=ce.Engine(task)
        assert q['reference']['optimal'] and q['reference']['proved_prefix']==6
        for label in ('reference','G','R4'):
            item=q[label] if label!='R4' else q[label]['result']
            v=engine.verify(item['decisions']);expected=item.get('objective') or q[label]['score']['objective']
            assert v['admissible'] and ce.compare(v['objective'],expected)==0
            counts['window_plans']+=1
    assert counts['window_plans']==18
    return {'status':'PASS','coverage':dict(counts)}

def existing_check(group,out):
    if group=='core_diagnostics':
        m=module('arco_stage_research_20261009/scripts','analyze_core');m.OUT=out;m.main()
        return read(out/'core_summary.json')
    if group=='scope':
        m=module('arco_contribution_20261011/scripts','reproduce')
        m.write=lambda path,value:write(out/Path(path).name,value)
        return m.verify()
    if group=='candidate_diagnostics':
        m=module('arco_core_revision_20261023/scripts','validate_candidates')
        m.write=lambda name,value:write(out/name,value)
        original_csv=m.csvwrite
        def csvwrite(name,rows):
            import csv
            with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,list(rows[0]));w.writeheader()
                w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)
        m.csvwrite=csvwrite;m.notes=lambda *args:None;m.main()
        return read(out/'candidates_validation.json')
    if group=='origin_target':
        m=module('arco_core_revision_20261023/scripts','validate_origin_target_panel')
        m.write=lambda path,value:write(out/Path(path).name,value);m.main()
        result=read(out/'origin_target_validation.json')
        panel=read(STUDIES/'arco_core_revision_20261023/analysis/origin_target_panel.json')
        exact=sum(q['lower_bound']==q['upper_bound'] for q in panel)
        assert exact==108 and len(panel)-exact==20
        result.update(exact_scalar_positions=exact,interval_scalar_positions=len(panel)-exact)
        return {k:v for k,v in result.items() if k not in ('cases','plan_records','historical_summary_bound_audits','negative_joint_certificate_audits')}
    if group=='capacity':
        # This established checker has a single derived write at module scope.
        original=Path.write_text
        def redirect(path,data,*args,**kwargs):
            if path.name=='capacity_reuse_verified.json':
                return original(out/path.name,data,*args,**kwargs)
            raise RuntimeError('Unexpected write in saved capacity check: '+str(path))
        from unittest.mock import patch
        with patch.object(Path,'write_text',redirect):
            runpy.run_path(str(STUDIES/'arco_core_revision_20261023/scripts/verify_capacity_reuse.py'),run_name='__main__')
        r=read(out/'capacity_reuse_verified.json')
        return {'status':r['status'],'cases':r['cases'],'new_solves':r['new_solves']}
    raise ValueError(group)

def adds_check(out):
    root=STUDIES/'arco_adds_external_20261024'
    r=module('arco_adds_external_20261024/scripts','run_deterministic')
    ce=r.ce;changes=r.changes;target_met=r.target_met
    frozen=read(root/'instances/FROZEN.json');assert len(frozen['tasks'])==15
    counts=collections.Counter();quality_counts=collections.Counter();formal={}
    for item in frozen['tasks']:
        path=root/item['task_path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        task=read(path);rid=item['record_id'];engine=ce.Engine(task)
        ref=read(root/'runs/deterministic'/f'{rid}__Full-MILP.json')
        assert ref['global_optimal'] and len(ref['phases'])==6 and all(p['proved'] for p in ref['phases'])
        origin=read(root/'runs/deterministic'/f'{rid}__G.json')['decisions'];formal[rid]=(task,origin,ref)
        for method in ('G','R4','R_frac','Iter-R4','Full-MILP'):
            saved=read(root/'runs/deterministic'/f'{rid}__{method}.json');score=engine.verify(saved['decisions'])
            assert score['admissible'] and ce.compare(score['objective'],saved['objective'])==0
            quality_counts[method]+=ce.quality(score['objective'],ref['objective']);counts['deterministic_plans']+=1
        for prefix in (2,3,4,6):
            for suffix in ('missions','chains','joint_k0','joint_k1','joint_k2','joint_k3'):
                q=read(root/'runs/coordination'/f'{rid}__T{prefix}__{suffix}.json');counts['scope_query_records']+=1
                assert q['status'] in ('optimal','infeasible')
                if q['decisions'] is None:
                    assert q['status']=='infeasible';continue
                score=engine.verify(q['decisions']);assert score['admissible'] and target_met(score['objective'],ref['objective'],prefix)
                ms,us=changes(q['decisions'],origin)
                assert len(ms)==q['mission_changes'] and len(us)==q['chain_changes']
                assert q['lower_bound']==q['upper_bound']
                assert q['chain_budget'] is None or len(us)<=q['chain_budget']
    assert dict(quality_counts)=={'G':7,'R4':10,'R_frac':10,'Iter-R4':11,'Full-MILP':15}
    scorer=importlib.import_module('score_adds_candidates')
    scorer.write=lambda path,value:write(out/Path(path).name,value)
    scorer.main(root/'runs/generation',root/'runs/deterministic',out)
    scored=read(out/'scores.json');assert len(scored)==30
    for row in scored:
        task,origin,ref=formal[row['record_id']]
        assert row['complete_decisions'] and row['admissible'];counts['model_plans']+=1
    selector=importlib.import_module('replay_selection')
    selector.write=lambda path,value:write(out/Path(path).name,value);selector.main()
    selected=read(out/'selection_replay.json');assert len(selected['rows'])==300;counts['selector_rows']=300
    expected=read(root/'analysis/selection_replay.json')
    assert selected['rows']==expected['rows']
    diag=read(root/'analysis/candidate_diagnostics.json')
    assert diag['complete_miss_denominator']==2 and diag['category_counts']=={'same_scope_attainable':1,'task_budget_insufficient_within_chainset':1}
    for row in diag['candidates']:
        task,origin,ref=formal[row['record_id']]
        for path in row['query_paths'].values():
            q=read(root/path);counts['candidate_scope_queries']+=1
            assert q['feasible'] is not None
            if q['decisions'] is None:
                assert q['feasible'] is False and q['status']=='infeasible';continue
            score=ce.Engine(task).verify(q['decisions']);assert score['admissible'] and target_met(score['objective'],ref['objective'],6)
            ms,us=changes(q['decisions'],origin);assert set(us)<=set(q['allowed_uavs'])
            assert q['task_budget'] is None or len(ms)<=q['task_budget']
    capacity=importlib.import_module('run_capacity_sensitivity')
    for rid,(task,origin,oldref) in formal.items():
        folder=root/'runs/capacity_sensitivity'/rid
        meta=read(folder/'summary.json');newtask=read(root/meta['expanded_task_path']);newref=read(folder/'new_reference.json')
        assert newref['global_optimal'];score=ce.Engine(newtask).verify(newref['decisions'])
        assert score['admissible'] and ce.compare(score['objective'],newref['objective'])==0
        counts['capacity_reference_plans']+=1
        for mode,target in (('old_lex',oldref['objective']),('new_T6',newref['objective'])):
            for path in folder.glob(mode+'_*.json'):
                q=read(path);capacity.verify_query(q,newtask,origin,target,mode);counts['capacity_query_records']+=1
    pilot=root/'runs/design_pilot'
    for index,name in enumerate(('grid1','grid05')):
        task=read(pilot/(name+'_task.json'));ref=read(pilot/(name+'_task_reference.json'));engine=ce.Engine(task)
        score=engine.verify(ref['decisions']);assert ref['global_optimal'] and score['admissible'] and ce.compare(score['objective'],ref['objective'])==0
        counts['grid_reference_plans']+=1
        for path in pilot.glob(f'grid{index}_T*_*.json'):
            if not path.name.startswith(f'grid{index}_T'):continue
            q=read(path);score=engine.verify(q['decisions']);assert score['admissible'] and target_met(score['objective'],ref['objective'],q['target_prefix'])
            counts['grid_query_records']+=1
    coarse=read(pilot/'grid1_task_reference.json')['objective'];fine=ce.Engine(read(pilot/'grid05_task.json'))
    for path in pilot.glob('fine_old_lex_*.json'):
        q=read(path);score=fine.verify(q['decisions']);assert score['admissible'] and ce.compare(score['objective'],coarse)<=0
        counts['grid_old_threshold_queries']+=1
    assert counts['scope_query_records']==360 and counts['capacity_query_records']==180
    assert counts['grid_query_records']==16 and counts['grid_old_threshold_queries']==2
    return {'status':'PASS','coverage':dict(counts),'reference_quality':dict(quality_counts),'conditions':15}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--group',choices=('all',)+GROUPS,default='all')
    p.add_argument('--output',type=Path,default=REPO/'local_results/studies')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if a.group=='all':
        results={}
        for group in GROUPS:
            subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--group',group,'--output',str(out)],check=True)
            results[group]=read(out/group/'SUMMARY.json')
        write(out/'SUMMARY.json',{'status':'PASS','network_calls':0,'optimizer_calls':0,'groups':results})
        print('PASS: all saved-study checks; network calls = 0; optimizer calls = 0.');return
    guard();target=out/a.group;target.mkdir(parents=True,exist_ok=True)
    captured=io.StringIO()
    with contextlib.redirect_stdout(captured):
        result=network_check() if a.group=='networks' else sensitivity_check() if a.group=='sensitivity' else adds_check(target) if a.group=='adds' else existing_check(a.group,target)
    write(target/'SUMMARY.json',result)
    print(json.dumps({'group':a.group,'status':result.get('status','PASS'),'coverage':result.get('coverage',result.get('scope',result.get('checks',{})))},ensure_ascii=False))

if __name__=='__main__':main()
