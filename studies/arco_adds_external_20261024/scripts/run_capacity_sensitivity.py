"""All-condition capacity sensitivity, with original formal G held fixed.

Only the locker movement capacity changes from 2 to 3 per one-minute window.
No formal task, model output, incumbent, reference, or runtime file is edited.
Every reference/query is saved separately and reused on restart.
"""
from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,json,time
from run_deterministic import ROOT,read,write,digest,ce,CoordinationProblem,changes,target_met,run_one

OUT=ROOT/'runs/capacity_sensitivity';OUT.mkdir(parents=True,exist_ok=True)
ce.HERE=OUT
def signature(plan):return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def relative(path):return Path(path).relative_to(ROOT).as_posix()
def fmt(q):
    lo,hi=q['lower_bound'],q['upper_bound']
    if hi is None:return 'infeasible' if q['status']=='infeasible' else 'unknown'
    return str(hi) if lo==hi else f'[{lo},{hi}]'

def verify_query(q,task,origin,target,mode):
    assert q['task_sha256']==signature(task)
    assert q['origin_sha256']==signature(origin)
    assert q['target_objective']==target
    if q['decisions'] is not None:
        score=ce.Engine(task).verify(q['decisions']);assert score['admissible'],score['errors']
        assert ce.compare(score['objective'],q['objective'])==0
        assert ce.compare(score['objective'],target)<=0 if mode=='old_lex' else target_met(score['objective'],target,6)
        ms,us=changes(q['decisions'],origin)
        assert (len(ms),len(us))==(q['mission_changes'],q['chain_changes'])
        assert q.get('chain_budget') is None or len(us)<=q['chain_budget']
        assert q.get('task_budget') is None or len(ms)<=q['task_budget']
        assert set(us)<=set(q['allowed_uavs'])
        if q['minimize']=='missions':assert q['upper_bound']==len(ms)
        if q['minimize']=='chains':assert q['upper_bound']==len(us)
        assert q['lower_bound']<=q['upper_bound']
    return q

def query(cp,task,origin,target,mode,metric,path,witnesses,chain_cap=None):
    if path.exists():return verify_query(read(path),task,origin,target,mode)
    if mode=='old_lex':
        result=cp.solve_lex_threshold(target,minimize=metric,chain_budget=chain_cap,seconds=60.,witness=witnesses)
        calls=result['solver_calls']
    else:
        result=cp.solve(target,target_prefix=6,minimize=metric,chain_budget=chain_cap,seconds=60.,witness=witnesses)
        calls=int(result['solver_seconds']>0)
    result.update(task_sha256=signature(task),origin_sha256=signature(origin),
                  solver_calls_for_record=calls,query_path=relative(path))
    verify_query(result,task,origin,target,mode);write(path,result)
    return result

def derive_cap_query(cp,task,origin,target,mode,c,marginals,path):
    """An unrestricted bound plus a fitting witness may close a restriction."""
    if path.exists():return verify_query(read(path),task,origin,target,mode)
    mission,chain=marginals['missions'],marginals['chains']
    if chain['lower_bound'] is not None and c<chain['lower_bound']:
        result=dict(protocol='derived_chain_lower_exclusion_v1',record_id=task['record_id'],origin_name='fixed_formal_G',
                    target_mode=mission['target_mode'],target_objective=target,minimize='missions',chain_budget=c,
                    task_budget=None,allowed_uavs=cp.uavs,status='infeasible',feasible=False,optimal=False,
                    lower_bound=None,upper_bound=None,decisions=None,objective=None,mission_changes=None,chain_changes=None,
                    derivation='Chain cap is smaller than the valid unrestricted chain lower bound',
                    source_query=chain['query_path'],source_chain_lower=chain['lower_bound'])
    elif mission['decisions'] is not None and mission['chain_changes']<=c:
        result=copy.deepcopy(mission);result.update(chain_budget=c,
          derivation='Unrestricted mission lower bound applies to the subset; its verified best witness meets this chain cap',
          source_query=mission['query_path'])
        # Original branch logs describe the source query, not another run.
        result.pop('branches',None)
    else:return None
    result.update(task_sha256=signature(task),origin_sha256=signature(origin),query_path=relative(path),
                  solver_calls_for_record=0,solver_seconds=0.,elapsed_seconds=0.)
    verify_query(result,task,origin,target,mode);write(path,result);return result

def main():
    started=time.perf_counter();manifest_path=ROOT/'instances/FROZEN.json';manifest=read(manifest_path)
    assert manifest['frozen'] and len(manifest['tasks'])==15
    sources={relative(manifest_path):digest(manifest_path)};metadata_updates=[]
    for item in manifest['inputs']:
        p=ROOT/item['path'];actual=digest(p)
        if actual!=item['sha256']:
            assert item['path'] in ('analysis/candidate_driver_checks.json','analysis/pipeline_protocol.json'),item['path']
            metadata_updates.append(dict(path=item['path'],frozen_sha256=item['sha256'],current_sha256=actual,
               role='Candidate-protocol metadata; not used by capacity optimization. Already changed before this sensitivity.'))
        sources[item['path']]=actual
    design_path=OUT/'design.json'
    design=dict(scope='All 15 frozen formal conditions, including all five controls',record_ids=[r['record_id'] for r in manifest['tasks']],
      intervention='Only resources.pad[locker_id]: 2 to 3 movements per unchanged one-minute window',
      fixed=['original formal G','incumbent','source parcels and geometry','assignment and chain order','due times',
             '0.5 minute departure grid','one-minute resource windows','closures','aircraft and complete-sortie rules'],
      targets=['fixed original lexicographic no-worse threshold','expanded-domain new reference quality'],
      query_seconds=60.,reference_seconds=60.,formal_requests=0,frozen_manifest_sha256=digest(manifest_path))
    if design_path.exists():
        saved=read(design_path);assert all(saved[k]==value for k,value in design.items())
    else:write(design_path,dict(created_utc=datetime.now(timezone.utc).isoformat(),**design))
    old_scope=read(ROOT/'analysis/scope_panel.json')
    rows=[];all_queries=[]
    for item in manifest['tasks']:
        rid=item['record_id'];old_path=ROOT/item['task_path'];old_task=read(old_path)
        assert digest(old_path)==item['sha256'];sources[item['task_path']]=item['sha256']
        hub=item['locker_id'];assert old_task['resources']['pad'][hub]==2
        task=copy.deepcopy(old_task);task['resources']['pad'][hub]=3
        assert task['baseline']==old_task['baseline'] and task['intervention']==old_task['intervention']
        restored=copy.deepcopy(task);restored['resources']['pad'][hub]=2;assert restored==old_task
        task_path=OUT/'tasks'/f'{rid}.json'
        if task_path.exists():assert read(task_path)==task
        else:write(task_path,task)
        folder=OUT/rid;folder.mkdir(parents=True,exist_ok=True)
        original_g_path=ROOT/'runs/deterministic'/f'{rid}__G.json'
        original_ref_path=ROOT/'runs/deterministic'/f'{rid}__Full-MILP.json'
        sources[relative(original_g_path)]=digest(original_g_path);sources[relative(original_ref_path)]=digest(original_ref_path)
        original_g=read(original_g_path);old_ref=read(original_ref_path);origin=original_g['decisions']
        assert old_ref['global_optimal']
        old_engine,new_engine=ce.Engine(old_task),ce.Engine(task)
        old_g_score=old_engine.verify(origin);expanded_g_score=new_engine.verify(origin)
        assert old_g_score['admissible'] and expanded_g_score['admissible']
        assert old_g_score['objective']==expanded_g_score['objective']==original_g['objective']
        # Domain containment is checked at the option level as well as in the
        # one-field task comparison. No new G becomes the scope origin.
        sig=lambda engine:{(m,o['path_id'],o['depart_min'],o['charge_blocks']) for m,options in engine.options().items() for o in options}
        assert sig(old_engine)<=sig(new_engine)
        write(folder/'fixed_origin.json',dict(decisions=origin,origin_sha256=signature(origin),
              source=relative(original_g_path),source_sha256=digest(original_g_path),
              original_replay=old_g_score,expanded_replay=expanded_g_score))
        reference_path=folder/'new_reference.json'
        new_ref=run_one(task_path,'Full-MILP',reference_path,budget=60.)
        new_score=new_engine.verify(new_ref['decisions']);assert new_score['admissible']
        if new_ref['global_optimal']:assert ce.compare(new_score['objective'],old_ref['objective'])<=0
        cp=CoordinationProblem(task,origin,origin_name='fixed_formal_G')
        witnesses=[origin,old_ref['decisions'],new_ref['decisions']]
        targets={}
        for mode,target in [('old_lex',old_ref['objective']),('new_T6',new_ref['objective'])]:
            marginals={}
            for metric in ('missions','chains'):
                q=query(cp,task,origin,target,mode,metric,folder/f'{mode}_{metric}.json',witnesses)
                marginals[metric]=q;all_queries.append(q)
                if q['decisions'] is not None:witnesses.append(q['decisions'])
            capped=[]
            for cap in range(len(task['fleet'])+1):
                path=folder/f'{mode}_chain_cap_{cap}.json'
                q=derive_cap_query(cp,task,origin,target,mode,cap,marginals,path)
                if q is None:q=query(cp,task,origin,target,mode,'missions',path,witnesses,cap)
                capped.append(q);all_queries.append(q)
                if q['decisions'] is not None:witnesses.append(q['decisions'])
            witnessed={(q['mission_changes'],q['chain_changes']) for q in capped if q['decisions'] is not None}
            frontier=sorted(p for p in witnessed if not any(o!=p and o[0]<=p[0] and o[1]<=p[1] for o in witnessed))
            resolved=all(q['status'] in ('optimal','infeasible') for q in capped)
            targets[mode]=dict(objective=target,reference_proved_optimal=old_ref['global_optimal'] if mode=='old_lex' else new_ref['global_optimal'],
                marginals={metric:dict(lower_bound=q['lower_bound'],upper_bound=q['upper_bound'],status=q['status'],
                            witness_missions=q['mission_changes'],witness_chains=q['chain_changes'],query_path=q['query_path']) for metric,q in marginals.items()},
                chain_cap_queries=[dict(chain_cap=q['chain_budget'],lower_bound=q['lower_bound'],upper_bound=q['upper_bound'],status=q['status'],
                    mission_changes=q['mission_changes'],chain_changes=q['chain_changes'],query_path=q['query_path']) for q in capped],
                verified_nondominated_pairs=frontier,frontier_exact=resolved,
                marginal_pair_jointly_attained=all(q['lower_bound']==q['upper_bound'] and q['upper_bound'] is not None for q in marginals.values())
                    and (marginals['missions']['upper_bound'],marginals['chains']['upper_bound']) in witnessed)
        original_rows={r['metric']:dict(lower_bound=r['lower'],upper_bound=r['upper'],status=r['status'],query_path=r['query_path'])
                       for r in old_scope['rows'] if r['record_id']==rid and r['target']=='T6'}
        original_frontier=next(f for f in old_scope['joint_frontiers'] if f['record_id']==rid and f['target']=='T6')
        row=dict(record_id=rid,base_id=item['base_id'],condition=item['condition'],hub=hub,capacity_before=2,capacity_after=3,
           original_task_sha256=item['sha256'],expanded_task_path=relative(task_path),expanded_task_sha256=digest(task_path),
           only_capacity_changed=True,fixed_original_G=True,origin_sha256=signature(origin),
           original_quality=old_ref['objective'],expanded_quality=new_ref['objective'],expanded_reference_proved=new_ref['global_optimal'],
           quality_comparison=ce.compare(new_ref['objective'],old_ref['objective']),new_reference_path=relative(reference_path),
           original_scope=original_rows,original_frontier=original_frontier,targets=targets)
        write(folder/'summary.json',row);rows.append(row)
        print(json.dumps(dict(record_id=rid,new_reference_proved=new_ref['global_optimal'],quality_comparison=row['quality_comparison'],
              old_scope={m:fmt(q) for m,q in original_rows.items()},
              old_lex={m:fmt(q) for m,q in targets['old_lex']['marginals'].items()},
              new_quality={m:fmt(q) for m,q in targets['new_T6']['marginals'].items()})),flush=True)
    # Historical/formal files remain exactly as before this sensitivity.
    for path,expected in sources.items():assert digest(ROOT/path)==expected,path
    scalar=[q for q in all_queries if q['chain_budget'] is None]
    output=dict(status='PASS',design=read(design_path),conditions=len(rows),base_delivery_instances=5,controls=5,
       rows=rows,all_new_references_proved=all(r['expanded_reference_proved'] for r in rows),
       scalar_positions=len(scalar),scalar_exact=sum(q['lower_bound']==q['upper_bound'] and q['upper_bound'] is not None for q in scalar),
       chain_cap_positions=sum(q['chain_budget'] is not None for q in all_queries),
       exact_frontiers=sum(t['frontier_exact'] for r in rows for t in r['targets'].values()),
       query_solver_calls=sum(q['solver_calls_for_record'] for q in all_queries),query_solver_seconds=sum(q['solver_seconds'] for q in all_queries),
       improved_references=sum(r['quality_comparison']<0 for r in rows),same_references=sum(r['quality_comparison']==0 for r in rows),
       numerical_frozen_inputs_unchanged=True,source_hashes_unchanged_during_sensitivity=True,
       preexisting_candidate_metadata_updates=metadata_updates,formal_source_hashes=sources,elapsed_this_run_seconds=time.perf_counter()-started,
       counting='15 related conditions from five locker delivery instances; all conditions retained; no candidate generation or model comparisons.')
    write(ROOT/'analysis/capacity_sensitivity.json',output)
    lines=['# 柜点动作容量 2→3：全 15 条件敏感性','',
      '在五个柜服务区的全部正式条件上，把每分钟柜点动作容量从 2 增至 3；固定原 G、incumbent、源需求、0.5 分钟出发网格、1 分钟预约窗口、时限、装卸返航规则及关闭区间。容量是预约窗口动作数，未解释为实体起降设施数。',
      '',f"15 个新参考中 {sum(r['expanded_reference_proved'] for r in rows)} 个六层最优已证明。相对原参考，{output['improved_references']} 个词典序改善、{output['same_references']} 个相同。60 个边际范围位置中 {output['scalar_exact']} 个闭合；30 个目标的联合预算前沿中 {output['exact_frontiers']} 个精确。",'',
      '| 条件 | 原容量 T6（任务/链） | 扩容达到旧 lex 门槛 | 扩容达到新 T6 | 旧质量 L3→新 L3 | 旧 L4→新 L4 |',
      '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        pair=lambda m:fmt(m['missions'])+'/'+fmt(m['chains'])
        old,new=row['original_quality'],row['expanded_quality']
        lines.append(f"| {row['record_id'].replace('ADDS_','')} | {pair(row['original_scope'])} | {pair(row['targets']['old_lex']['marginals'])} | {pair(row['targets']['new_T6']['marginals'])} | {old['repair_distance']:.3g}→{new['repair_distance']:.3g} | {old['weighted_tardiness_min']:.3g}→{new['weighted_tardiness_min']:.3g} |")
    lines += ['', '每格为两个边际最小值或有效区间；能否共同达到，以及所有非支配预算对，见下表。固定旧门槛按原容差下的词典序不劣判定，不是要求每层均不差；新 T6 匹配扩容后的参考质量。', '',
       '| 条件 | 原 T6 联合前沿 | 扩容旧门槛联合前沿 | 扩容新 T6 联合前沿 |', '|---|---|---|---|']
    for row in rows:
        pairs=lambda p:', '.join(f'({a},{b})' for a,b in p)
        lines.append(f"| {row['record_id'].replace('ADDS_','')} | {pairs(row['original_frontier']['verified_pareto_pairs'])} | {pairs(row['targets']['old_lex']['verified_nondominated_pairs'])} | {pairs(row['targets']['new_T6']['verified_nondominated_pairs'])} |")
    lines += ['', '精确性由所有链上限 0、1、2、3 的任务最小值或不可达结果共同支持。已有无约束下界与符合该链上限的见证可直接闭合；低于最少链数下界的预算直接排除。其余情况调用受限查询，每次不超过 60 秒，结果保存后复用。', '',
       f"范围查询实际调用求解器 {output['query_solver_calls']} 次，累计求解器时间 {output['query_solver_seconds']:.3f} 秒；另有 15 份参考求解记录。此处不是新模型评价。冻结的实例与数值运行时保持不变，实际读取文件在本次敏感性运行前后均未改变。", '',
       '候选驱动检查与候选协议 JSON 在本次运行前已有两个元数据更新，已在结构化结果中记录原/现哈希；它们不进入容量求解。冻结清单没有被改写。', '',
       '具体任务、固定起点、参考、逐查询分支与见证保存在 `runs/capacity_sensitivity/`；汇总为 `analysis/capacity_sensitivity.json`。前沿有界未闭合时，`frontier_exact=false`，表内预算只作经验证的非支配候选，不称已穷尽的最优前沿。','']
    (ROOT/'analysis/capacity_sensitivity.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:output[k] for k in ('status','conditions','all_new_references_proved','scalar_positions','scalar_exact','chain_cap_positions','exact_frontiers','improved_references','same_references','query_solver_calls','query_solver_seconds')}),flush=True)
if __name__=='__main__':main()
