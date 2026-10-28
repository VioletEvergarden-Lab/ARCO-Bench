"""Direct target-conditioned coordination MILP; an existing-method baseline.

Unchanged public finite options and independent event verifier are reused.
Target prefixes use equality within the archived quality tolerances. Distance
from G (or a supplied origin) is separate from incumbent-relative objective L3.
"""
from pathlib import Path
import json, math, sys, time
from datetime import datetime, timezone
import numpy as np
from scipy.sparse import coo_matrix, csr_matrix, hstack, vstack
sys.dont_write_bytecode=True
from continuous_engine import Engine, TIERS, QUALITY_TOL
from solver_backend import highspy, VERSION
FIELDS=('held','path_id','depart_min','charge_blocks')
PROTOCOL='target_coordination_direct_v1'


def canonical_plan(plan,task):
    if isinstance(plan,dict): plan=plan['decisions']
    mm={m['mission_id']:m for m in task.get('instance',task)['missions']}
    time_field='depart_slot' if 'instance' in task else 'depart_min'
    if len(plan)!=len(mm) or {d['mission_id'] for d in plan}!=set(mm):
        raise ValueError('Plan must cover every mission exactly once')
    out=[]
    for d in plan:
        mid=d['mission_id'];uid=mm[mid]['uav_id']
        if d.get('uav_id',uid)!=uid or type(d['held']) is not bool:
            raise ValueError(('decision schema',mid))
        out.append(dict(mission_id=mid,uav_id=uid,held=d['held'],
            path_id=None if d['held'] else d['path_id'],
            **{time_field:None if d['held'] else d[time_field]},
            charge_blocks=0 if d['held'] else d['charge_blocks']))
    return sorted(out,key=lambda d:d['mission_id'])


def changes(plan,origin):
    before={d['mission_id']:d for d in origin}
    fields=('held','path_id','depart_slot' if 'depart_slot' in plan[0] else 'depart_min','charge_blocks')
    ms=sorted(d['mission_id'] for d in plan if any(d[k]!=before[d['mission_id']][k] for k in fields))
    return ms,sorted({d['uav_id'] for d in plan if d['mission_id'] in ms})


def target_met(objective,target,prefix,target_mode='match',tolerances=QUALITY_TOL):
    if objective is None:return False
    return all((abs(objective[t]-target[t]) if target_mode=='match' else objective[t]-target[t])
        <=tolerances[i]+1e-10 for i,t in enumerate(TIERS[:prefix]))


class CoreEngine:
    """Thin adapter to the archived Core public-domain builder and evaluator."""
    quality_tolerance=(0.,0.,0.,0.,0.,1e-4)
    # The public Core evaluator rounds energy to six decimals. Use the same
    # accepted rounding cells as archived analyze_coordination.py.
    row_tolerance=(0.,0.,0.,0.,0.,1e-4+0.5e-6-1e-9)
    def __init__(self,task):
        from study_common import Runtime
        self.task=task;self.runtime=Runtime();inst=task['instance']
        self.fleet={u['uav_id']:u for u in inst['fleet']}
        self.missions={m['mission_id']:m for m in inst['missions']}
        self.chains={u:sorted([m for m in inst['missions'] if m['uav_id']==u],key=lambda m:m['sequence_index']) for u in self.fleet}
    def build(self):
        b=self.runtime.build(self.task);self.original_built=b
        costs=np.array([dict(b['tiers'])[t] for t in TIERS])
        return dict(A=b['A'].tocsr(),lb=b['lb'],ub=b['ub'],meta=b['var_meta'],
            indices=b['option_indices'],holds=b['hold_idx'],costs=costs,
            scales=np.ones(6),variables=len(b['var_meta']),base_rows=b['A'].shape[0])
    def extract(self,built,x):
        from common import extract
        return extract(self.original_built,x)
    def verify(self,plan):
        z=self.runtime.evaluate(self.task,plan)
        return dict(admissible=bool(z['formal_feasible']),objective=z.get('objective_vector'),
            errors=z.get('formal_errors',[]))


class CoordinationProblem:
    """Reusable model for one task/origin. prepare() is lazy and separately timed.

    solve elapsed includes query construction, solver and independent validation;
    on the first solve it also includes the base build. Constructor time is in
    preparation_seconds and wrapper solve_coordination includes it in elapsed.
    """
    def __init__(self,task,origin,origin_name='supplied'):
        start=time.perf_counter()
        self.task=task;self.origin=canonical_plan(origin,task);self.origin_name=origin_name
        self.engine=CoreEngine(task) if 'instance' in task else Engine(task);self.built=None
        self.fields=('held','path_id','depart_slot' if 'instance' in task else 'depart_min','charge_blocks')
        self.tolerances=getattr(self.engine,'quality_tolerance',QUALITY_TOL)
        self.row_tolerances=getattr(self.engine,'row_tolerance',self.tolerances)
        self.uavs=sorted(self.engine.fleet);self.mids=sorted(self.engine.missions)
        self.preparation_seconds=time.perf_counter()-start

    def prepare(self):
        if self.built is not None:return self
        start=time.perf_counter();b=self.engine.build();n=b['variables'];self.n_options=n
        self.y={mid:n+i for i,mid in enumerate(self.mids)}
        self.z={u:n+len(self.mids)+i for i,u in enumerate(self.uavs)}
        self.n=n+len(self.mids)+len(self.uavs)
        rr=[];cc=[];vv=[];lo=[];hi=[]
        def row(items,l=-np.inf,h=np.inf):
            ri=len(lo)
            for col,val in items:
                if val:rr.append(ri);cc.append(col);vv.append(val)
            lo.append(l);hi.append(h)
        by={d['mission_id']:d for d in self.origin}
        for mid in self.mids:
            d=by[mid]
            matches=([b['holds'][mid]] if d['held'] else [i for i in b['indices'][mid]
                if all(b['meta'][i][key]==d[key] for key in self.fields[1:])])
            if len(matches)>1:raise RuntimeError(('nonunique option',mid))
            # If the disrupted domain excludes the origin action, y is fixed 1.
            row([(self.y[mid],1)]+[(i,1) for i in matches],1,1)
            row([(self.y[mid],1),(self.z[self.engine.missions[mid]['uav_id']],-1)],h=0)
        for u in self.uavs:
            row([(self.z[u],1)]+[(self.y[m['mission_id']],-1) for m in self.engine.chains[u]],h=0)
        extra=coo_matrix((vv,(rr,cc)),shape=(len(lo),self.n)).tocsr()
        base=hstack([b['A'],csr_matrix((b['A'].shape[0],self.n-n))],format='csr')
        self.A=vstack([base,extra],format='csr');self.lb=np.r_[b['lb'],lo];self.ub=np.r_[b['ub'],hi]
        self.built=b;self.preparation_seconds+=time.perf_counter()-start
        return self

    def solve_lex_threshold(self,target_objective,minimize='missions',allowed_uavs=None,
                            task_budget=None,chain_budget=None,seconds=60.,witness=None):
        from lex_query import solve_lex_threshold
        return solve_lex_threshold(self,target_objective,minimize,allowed_uavs,task_budget,chain_budget,seconds,witness)

    def _x(self,plan):
        x=np.zeros(self.n)
        for d in plan:
            mid=d['mission_id'];b=self.built
            matches=([b['holds'][mid]] if d['held'] else [i for i in b['indices'][mid]
                if all(b['meta'][i][k]==d[k] for k in self.fields[1:])])
            if len(matches)!=1:return None
            x[matches[0]]=1
        ms,us=changes(plan,self.origin)
        for m in ms:x[self.y[m]]=1
        for u in us:x[self.z[u]]=1
        return x

    def solve(self,target_objective,target_prefix=6,minimize='missions',allowed_uavs=None,
              task_budget=None,chain_budget=None,seconds=60.,witness=None,no_good_supports=None,target_mode='match'):
        if target_prefix not in range(1,7):raise ValueError('prefix must be 1..6')
        if minimize not in ('missions','chains','feasibility'):raise ValueError(minimize)
        if seconds<0:raise ValueError('negative seconds')
        if target_mode not in ('match','ceiling'):raise ValueError(target_mode)
        start=time.perf_counter();stamp=datetime.now(timezone.utc).isoformat()
        allowed=set(self.uavs if allowed_uavs is None else allowed_uavs)
        if not allowed<=set(self.uavs):raise ValueError('unknown allowed UAV')
        for budget in (task_budget,chain_budget):
            if budget is not None and (type(budget) is not int or budget<0):raise ValueError('invalid budget')
        excluded=[set(s) for s in (no_good_supports or [])]
        if any(not s<=set(self.uavs) for s in excluded):raise ValueError('unknown excluded support UAV')
        target={t:float(target_objective[t]) for t in TIERS}
        best=None;bestscore=None;bestvalue=None;bestsource=None;validation=0.;rejected=[]
        def accept(plan,source):
            nonlocal best,bestscore,bestvalue,bestsource,validation
            tick=time.perf_counter();plan=canonical_plan(plan,self.task);score=self.engine.verify(plan)
            ms,us=changes(plan,self.origin)
            ok=(score['admissible'] and target_met(score['objective'],target,target_prefix,target_mode,self.tolerances)
                and set(us)<=allowed and (task_budget is None or len(ms)<=task_budget)
                and (chain_budget is None or len(us)<=chain_budget) and all(set(us)!=s for s in excluded))
            validation+=time.perf_counter()-tick
            if not ok:
                rejected.append(dict(source=source,admissible=score['admissible'],errors=score['errors'],
                    target_met=target_met(score['objective'],target,target_prefix,target_mode,self.tolerances)))
                return
            val=len(ms) if minimize=='missions' else len(us) if minimize=='chains' else 0
            if bestvalue is None or val<bestvalue:best,bestscore,bestvalue,bestsource=plan,score,val,source
        accept(self.origin,'origin')
        if witness is not None:
            plans=witness if isinstance(witness,list) and witness and isinstance(witness[0],list) else [witness]
            for i,p in enumerate(plans):accept(p,'supplied_witness_'+str(i))
        prep_before=self.preparation_seconds
        analytic_lower=0 if minimize=='feasibility' or bestvalue==0 else 1
        solver_seconds=0.;lower=analytic_lower;dual=None;message='No MIP needed';optimal=False;nodes=0;query_rows=0
        solver_objective=None
        if bestvalue is not None and bestvalue==analytic_lower:
            optimal=True;status='feasible' if minimize=='feasibility' else 'optimal'
        elif time.perf_counter()-start>=seconds:
            status='feasible_unproven' if best is not None else 'unknown';message='Budget exhausted before build'
        else:
            self.prepare();rr=[];cc=[];vv=[];lo=[];hi=[]
            def row(items,l=-np.inf,h=np.inf):
                ri=len(lo)
                for col,val in items:
                    if val:rr.append(ri);cc.append(col);vv.append(val)
                lo.append(l);hi.append(h)
            for i,tier in enumerate(TIERS[:target_prefix]):
                cost=self.built['costs'][i].copy();value=target[tier]*self.built['scales'][i]
                if i==2 and target_mode=='match' and 'instance' not in self.task:
                    cost-=1000*self.built['scales'][2]*self.built['costs'][1]
                    value-=1000*self.built['scales'][2]*target[TIERS[1]]
                tol=self.row_tolerances[i]*self.built['scales'][i]
                row(enumerate(cost),value-tol if target_mode=='match' else -np.inf,value+tol)
            for u in self.uavs:
                if u not in allowed:row([(self.z[u],1)],0,0)
            if task_budget is not None:row([(i,1) for i in self.y.values()],h=task_budget)
            if chain_budget is not None:row([(i,1) for i in self.z.values()],h=chain_budget)
            for support in excluded:row([(i,1 if u in support else -1) for u,i in self.z.items()],h=len(support)-1)
            query_rows=len(lo)
            extra=coo_matrix((vv,(rr,cc)),shape=(query_rows,self.n)).tocsr()
            A=vstack([self.A,extra],format='csr');lb=np.r_[self.lb,lo];ub=np.r_[self.ub,hi]
            c=np.zeros(self.n)
            if minimize!='feasibility':c[list((self.y if minimize=='missions' else self.z).values())]=1
            remaining=seconds-(time.perf_counter()-start)
            if remaining<=0:
                status='feasible_unproven' if best is not None else 'unknown';message='Budget exhausted during build'
            else:
                h=highspy.Highs()
                for key,val in [('output_flag',False),('threads',1),('time_limit',remaining),('mip_rel_gap',0.),
                                ('mip_abs_gap',0.),('mip_feasibility_tolerance',1e-7),('presolve','on'),('random_seed',0)]:
                    if h.setOptionValue(key,val)!=highspy.HighsStatus.kOk:raise RuntimeError(key)
                lp=highspy.HighsLp();lp.num_col_=self.n;lp.num_row_=A.shape[0];lp.col_cost_=c
                lp.col_lower_=np.zeros(self.n);lp.col_upper_=np.ones(self.n);lp.row_lower_=lb;lp.row_upper_=ub
                lp.a_matrix_.format_=highspy.MatrixFormat.kRowwise;lp.a_matrix_.start_=A.indptr.astype(np.int32)
                lp.a_matrix_.index_=A.indices.astype(np.int32);lp.a_matrix_.value_=A.data
                lp.integrality_=[highspy.HighsVarType.kInteger]*self.n
                if h.passModel(lp)==highspy.HighsStatus.kError:raise RuntimeError('passModel')
                if best is not None:
                    x=self._x(best)
                    if x is not None:
                        ss=highspy.HighsSolution();ss.col_value=x;ss.value_valid=True;h.setSolution(ss)
                h.setOptionValue('time_limit',max(0.,seconds-(time.perf_counter()-start)))
                tick=time.perf_counter();h.run();solver_seconds=time.perf_counter()-tick
                info=h.getInfo();sol=h.getSolution();code=h.getModelStatus();message=h.modelStatusToString(code)
                nodes=int(info.mip_node_count)
                if np.isfinite(info.mip_dual_bound):dual=float(info.mip_dual_bound)
                if dual is not None:lower=max(analytic_lower,math.ceil(dual-1e-6))
                if info.primal_solution_status==highspy.SolutionStatus.kSolutionStatusFeasible and sol.value_valid:
                    x=np.asarray(sol.col_value)
                    if np.max(np.abs(x-np.rint(x)))<=1e-5:
                        solver_objective=float(c@np.rint(x))
                        accept(self.engine.extract(self.built,np.rint(x[:self.n_options])),'MIP')
                if code==highspy.HighsModelStatus.kInfeasible:
                    if best is not None:raise RuntimeError('Proven infeasible contradicts verified witness')
                    status='infeasible';lower=None
                elif best is not None:
                    if lower>bestvalue:raise RuntimeError(('Lower exceeds verified upper',lower,bestvalue))
                    optimal=(lower==bestvalue)
                    status='feasible' if minimize=='feasibility' else 'optimal' if optimal else 'feasible_unproven'
                else:status='unknown'
        elapsed=time.perf_counter()-start;ms,us=changes(best,self.origin) if best is not None else (None,None)
        return dict(protocol=PROTOCOL,record_id=self.task['record_id'],origin_name=self.origin_name,
            target_prefix=target_prefix,target_mode=target_mode,target_objective=target,
            quality_tolerance=list(self.tolerances),minimize=minimize,allowed_uavs=sorted(allowed),
            task_budget=task_budget,chain_budget=chain_budget,no_good_supports=[sorted(s) for s in excluded],
            status=status,feasible=True if best is not None else False if status=='infeasible' else None,
            optimal=optimal,lower_bound=lower,upper_bound=bestvalue,raw_dual_bound=dual,
            analytic_distance_lower_bound=analytic_lower,
            solver_objective=solver_objective,decisions=best,objective=bestscore['objective'] if bestscore else None,
            changed_missions=ms,changed_uavs=us,mission_changes=len(ms) if ms is not None else None,
            chain_changes=len(us) if us is not None else None,witness_source=bestsource,
            independent_verification=best is not None,rejected_candidates=rejected,solver_status=message,
            solver_nodes=nodes,solver='HiGHS '+VERSION,solver_threads=1,started_utc=stamp,
            budget_seconds=seconds,elapsed_seconds=elapsed,query_build_seconds=max(0.,elapsed-solver_seconds-validation),
            base_build_seconds_in_query=self.preparation_seconds-prep_before,
            preparation_seconds_cumulative=self.preparation_seconds,solver_seconds=solver_seconds,
            validation_seconds=validation,completed_within_budget=elapsed<=seconds,
            variables=self.n if self.built else None,constraints=self.A.shape[0]+query_rows if self.built else None)


def solve_coordination(task,target_objective,origin,target_prefix=6,minimize='missions',allowed_uavs=None,
                       task_budget=None,chain_budget=None,seconds=60.,witness=None,origin_name='supplied',no_good_supports=None,target_mode='match'):
    start=time.perf_counter();problem=CoordinationProblem(task,origin,origin_name)
    out=problem.solve(target_objective,target_prefix,minimize,allowed_uavs,task_budget,chain_budget,
                      max(0.,seconds-(time.perf_counter()-start)),witness,no_good_supports,target_mode)
    out['elapsed_seconds']=time.perf_counter()-start;out['budget_seconds']=seconds
    out['completed_within_budget']=out['elapsed_seconds']<=seconds
    return out
