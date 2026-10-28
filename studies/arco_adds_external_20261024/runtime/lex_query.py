"""Valid scope bounds for the archived tolerance-aware lexicographic gate.

Closed first-better branch rows are outer relaxations of the strict comparator.
Their dual bounds therefore remain valid. A plan supplies an upper bound only
after independent replay and compare(objective,target)<=0. Boundary-only MIP
witnesses are rejected and the result retains a gap when necessary.
"""
import math,time
from datetime import datetime,timezone
import numpy as np
from scipy.sparse import coo_matrix,vstack
from continuous_engine import TIERS,compare
from solver_backend import solve as mip_solve,VERSION

def solve_lex_threshold(problem,target_objective,minimize='missions',allowed_uavs=None,
                        task_budget=None,chain_budget=None,seconds=60.,witness=None):
    if minimize not in ('missions','chains','feasibility'):raise ValueError(minimize)
    if seconds<0:raise ValueError('negative seconds')
    start=time.perf_counter();stamp=datetime.now(timezone.utc).isoformat()
    target={t:float(target_objective[t]) for t in TIERS}
    allowed=set(problem.uavs if allowed_uavs is None else allowed_uavs)
    if not allowed<=set(problem.uavs):raise ValueError('Unknown allowed UAV')
    for budget in (task_budget,chain_budget):
        if budget is not None and (type(budget) is not int or budget<0):raise ValueError('Invalid budget')
    from coordination_solver import canonical_plan,changes
    best=None;bestscore=None;bestvalue=None;source=None;rejected=[]
    def accept(plan,label):
        nonlocal best,bestscore,bestvalue,source
        ds=canonical_plan(plan,problem.task);score=problem.engine.verify(ds);ms,us=changes(ds,problem.origin)
        feasible=(score['admissible'] and compare(score['objective'],target)<=0 and set(us)<=allowed
                  and (task_budget is None or len(ms)<=task_budget) and (chain_budget is None or len(us)<=chain_budget))
        if not feasible:
            rejected.append(dict(source=label,admissible=score['admissible'],errors=score['errors'],
                                 lex_comparison=compare(score['objective'],target) if score['admissible'] else None))
            return
        value=len(ms) if minimize=='missions' else len(us) if minimize=='chains' else 0
        if bestvalue is None or value<bestvalue:best,bestscore,bestvalue,source=ds,score,value,label
    accept(problem.origin,'origin')
    if witness is not None:
        witnesses=witness if isinstance(witness,list) and witness and isinstance(witness[0],list) else [witness]
        for i,plan in enumerate(witnesses):accept(plan,'supplied_'+str(i))
    analytic_lower=0 if minimize=='feasibility' or bestvalue==0 else 1
    branches=[];solver_seconds=0.;lower=analytic_lower
    if bestvalue!=analytic_lower and time.perf_counter()-start<seconds:
        problem.prepare();cost=np.zeros(problem.n)
        if minimize!='feasibility':cost[list((problem.y if minimize=='missions' else problem.z).values())]=1
        for branch in range(7):
            remaining=seconds-(time.perf_counter()-start)
            if remaining<=0:
                branches.append(dict(branch=branch,status='not_run',lower_bound=analytic_lower));continue
            rr=[];cc=[];vv=[];lo=[];hi=[]
            def row(items,l=-np.inf,h=np.inf):
                r=len(lo)
                for col,val in items:
                    if val:rr.append(r);cc.append(col);vv.append(val)
                lo.append(l);hi.append(h)
            # 0..5: first strict improvement at this tier; 6: all tiers tied.
            impossible=False
            for i in range(6 if branch==6 else branch+1):
                coeff=problem.built['costs'][i]
                val=target[TIERS[i]]*problem.built['scales'][i]
                tol=problem.tolerances[i]*problem.built['scales'][i]
                if branch<6 and i==branch:
                    upper=val-tol
                    # L1/L2 and grid-scaled L3 are integer valued. Use their
                    # exact predecessor; relaxing an integer strict bound at
                    # zero would otherwise admit all service-tied plans.
                    lattice_exact=i<3
                    if lattice_exact:
                        if not np.allclose(coeff,np.rint(coeff),atol=1e-7,rtol=0):raise ValueError('Noninteger lex lattice')
                        coeff=np.rint(coeff)
                        upper=math.ceil(upper)-1
                    if upper<-1e-9 and np.all(coeff>=0):impossible=True
                    row(enumerate(coeff),h=upper)
                else:row(enumerate(coeff),val-tol,val+tol)
            for u in problem.uavs:
                if u not in allowed:row([(problem.z[u],1)],0,0)
            if task_budget is not None:row([(i,1) for i in problem.y.values()],h=task_budget)
            if chain_budget is not None:row([(i,1) for i in problem.z.values()],h=chain_budget)
            if impossible:
                branches.append(dict(branch=branch,status='infeasible',proof='nonnegative objective exceeds branch upper bound',lower_bound=None));continue
            extra=coo_matrix((vv,(rr,cc)),shape=(len(lo),problem.n)).tocsr()
            A=vstack([problem.A,extra],format='csr');lb=np.r_[problem.lb,lo];ub=np.r_[problem.ub,hi]
            initial=problem._x(best) if best is not None else None
            if initial is not None and (np.any(A@initial<lb-1e-8) or np.any(A@initial>ub+1e-8)):initial=None
            tick=time.perf_counter();result=mip_solve(cost,A,lb,ub,remaining,initial);elapsed=time.perf_counter()-tick;solver_seconds+=elapsed
            dual=result.mip_dual_bound;branch_lower=max(analytic_lower,math.ceil(dual-1e-6)) if dual is not None else analytic_lower
            record=dict(branch=branch,first_better_tier=TIERS[branch] if branch<6 else None,
                        status='infeasible' if result.status==2 else 'optimal_relaxation' if result.status==0 else 'bounded',
                        lower_bound=None if result.status==2 else branch_lower,raw_dual_bound=dual,
                        solver_status=result.message,solver_seconds=elapsed,strict_boundary_relaxed=3<=branch<6,
                        exact_integer_strict_bound=branch<3)
            if result.x is not None and np.max(np.abs(result.x-np.rint(result.x)))<=1e-5:
                ds=problem.engine.extract(problem.built,np.rint(result.x[:problem.n_options]))
                score=problem.engine.verify(ds)
                record.update(decisions=ds,objective=score['objective'],admissible=score['admissible'],
                              lex_comparison=compare(score['objective'],target) if score['admissible'] else None)
                accept(ds,'branch_'+str(branch))
            branches.append(record)
        viable=[r['lower_bound'] for r in branches if r['status']!='infeasible']
        lower=min(viable) if viable else None
    if branches and all(r['status']=='infeasible' for r in branches):
        if best is not None:raise RuntimeError('Lex outer union excludes a verified witness')
        status='infeasible';feasible=False;optimal=False
    elif best is not None:
        if lower is not None and lower>bestvalue:raise RuntimeError(('Lex bound exceeds verified witness',lower,bestvalue))
        optimal=lower==bestvalue;feasible=True
        status='feasible' if minimize=='feasibility' else 'optimal' if optimal else 'feasible_unproven'
    else:status='unknown';feasible=None;optimal=False
    ms,us=changes(best,problem.origin) if best is not None else (None,None)
    return dict(protocol='fixed_lex_threshold_outer_bounds_verified_witness_v1',record_id=problem.task['record_id'],
                origin_name=problem.origin_name,target_mode='fixed_lexicographic_no_worse',target_objective=target,
                quality_tolerance=list(problem.tolerances),minimize=minimize,allowed_uavs=sorted(allowed),
                task_budget=task_budget,chain_budget=chain_budget,status=status,feasible=feasible,optimal=optimal,
                lower_bound=lower,upper_bound=bestvalue,decisions=best,objective=bestscore['objective'] if bestscore else None,
                changed_missions=ms,changed_uavs=us,mission_changes=len(ms) if ms is not None else None,
                chain_changes=len(us) if us is not None else None,witness_source=source,rejected_candidates=rejected,
                branches=branches,solver_calls=sum('solver_seconds' in r for r in branches),solver_seconds=solver_seconds,
                elapsed_seconds=time.perf_counter()-start,budget_seconds=seconds,started_utc=stamp,solver='HiGHS '+VERSION,
                boundary_handling='Closed first-better rows give outer-union lower bounds; only compare<=0 independently replayed plans give upper bounds.')
