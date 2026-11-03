"""Sparse HiGHS interface with an integer start from the preceding tier."""
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent/'.solver_deps'))
import highspy
VERSION=highspy.Highs().version()

def solve(c,A,lower,upper,seconds,incumbent=None):
    h=highspy.Highs()
    for key,value in [('output_flag',False),('threads',1),('time_limit',float(seconds)),('mip_rel_gap',0.),('mip_abs_gap',0.),('mip_feasibility_tolerance',1e-7),('presolve','on'),('random_seed',0)]:
        if h.setOptionValue(key,value)!=highspy.HighsStatus.kOk: raise RuntimeError(('solver option',key))
    lp=highspy.HighsLp(); n=len(c)
    lp.num_col_=n; lp.num_row_=A.shape[0]; lp.col_cost_=c; lp.col_lower_=np.zeros(n); lp.col_upper_=np.ones(n); lp.row_lower_=lower; lp.row_upper_=upper
    lp.a_matrix_.format_=highspy.MatrixFormat.kRowwise; lp.a_matrix_.start_=A.indptr.astype(np.int32); lp.a_matrix_.index_=A.indices.astype(np.int32); lp.a_matrix_.value_=A.data
    lp.integrality_=[highspy.HighsVarType.kInteger]*n
    input_status=h.passModel(lp)
    if input_status==highspy.HighsStatus.kError: raise RuntimeError('pass sparse MILP')
    if incumbent is not None:
        solution=highspy.HighsSolution(); solution.col_value=np.rint(incumbent); solution.value_valid=True
        h.setSolution(solution)
    h.run(); status=h.getModelStatus(); info=h.getInfo(); solution=h.getSolution()
    code=0 if status==highspy.HighsModelStatus.kOptimal else 2 if status==highspy.HighsModelStatus.kInfeasible else 1 if status in (highspy.HighsModelStatus.kTimeLimit,highspy.HighsModelStatus.kIterationLimit,highspy.HighsModelStatus.kSolutionLimit) else 4
    feasible=info.primal_solution_status==highspy.SolutionStatus.kSolutionStatusFeasible and solution.value_valid
    return SimpleNamespace(status=code,x=np.array(solution.col_value) if feasible else None,mip_dual_bound=info.mip_dual_bound if np.isfinite(info.mip_dual_bound) else None,mip_gap=info.mip_gap if np.isfinite(info.mip_gap) else None,message=h.modelStatusToString(status),input_status=str(input_status))
