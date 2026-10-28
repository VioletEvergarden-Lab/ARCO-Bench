"""Sound reuse for target-conditioned support feasibility queries.

A cache belongs to one unchanged model, reference vector, and origin. It does
not cross resource interventions or origins. This is standard monotone
feasibility inference, not a claim of a new generic algorithm.
"""
from dataclasses import dataclass
from math import inf
from time import perf_counter

@dataclass(frozen=True)
class Query:
    prefix: int
    allowed: frozenset
    mission_budget: float = inf
    chain_budget: float = inf

    @classmethod
    def make(cls, prefix, allowed, mission_budget=None, chain_budget=None):
        return cls(int(prefix),frozenset(allowed),inf if mission_budget is None else int(mission_budget),inf if chain_budget is None else int(chain_budget))

@dataclass
class Witness:
    prefix: int
    support: frozenset
    missions: int
    decisions: list
    provenance: str

class FeasibilityCache:
    def __init__(self):
        self.witnesses=[]
        self.exclusions=[]
        self.inference_seconds=0.0

    def add_witness(self, prefix, support, missions, decisions, provenance):
        # Caller must independently validate the plan and the attained prefix.
        if prefix < 1: return
        self.witnesses.append(Witness(prefix,frozenset(support),int(missions),decisions,provenance))

    def add_exclusion(self, query, provenance):
        # Only a proved infeasibility may enter, never a timeout/no incumbent.
        self.exclusions.append((query,provenance))

    def infer(self, query):
        start=perf_counter()
        yes=next((w for w in self.witnesses if w.prefix>=query.prefix
            and w.support<=query.allowed and w.missions<=query.mission_budget
            and len(w.support)<=query.chain_budget),None)
        no=next(((q,p) for q,p in self.exclusions if q.prefix<=query.prefix
            and query.allowed<=q.allowed and query.mission_budget<=q.mission_budget
            and query.chain_budget<=q.chain_budget),None)
        self.inference_seconds+=perf_counter()-start
        if yes is not None and no is not None:
            raise AssertionError('A stored valid witness contradicts a stored exclusion')
        if yes is not None:
            return {'feasible':True,'evidence':'verified_witness_reuse','source':yes.provenance,'decisions':yes.decisions}
        if no is not None:
            return {'feasible':False,'evidence':'proved_exclusion_reuse','source':no[1]}
        return None


def self_test():
    """Check all inference directions against a finite target/support universe."""
    import itertools
    units=('A','B','C')
    supports=[frozenset(c) for n in range(4) for c in itertools.combinations(units,n)]
    # Explicit attainable plans; higher prefix implies every weaker prefix.
    plans=[(2,{'A'},1),(3,{'A','B'},2),(6,{'B','C'},3),(6,{'A','B','C'},4)]
    queries=[Query.make(j,s,k,c) for j in (2,3,6) for s in supports for k in range(5) for c in range(4)]
    def truth(q):
        return any(j>=q.prefix and set(s)<=q.allowed and k<=q.mission_budget and len(s)<=q.chain_budget for j,s,k in plans)
    cache=FeasibilityCache()
    for i,(j,s,k) in enumerate(plans):cache.add_witness(j,s,k,[{'synthetic':i}],f'p{i}')
    for q in queries:
        if not truth(q):cache.add_exclusion(q,'exhaustive finite universe')
    for q in queries:
        result=cache.infer(q)
        assert result is not None and result['feasible']==truth(q)
    # A stronger-target exclusion cannot be reused for a weaker target.
    cache=FeasibilityCache();cache.add_exclusion(Query.make(6,{'A'}),'q6')
    assert cache.infer(Query.make(2,{'A'})) is None
    # A narrower exclusion cannot be reused for an expanded support/budget.
    assert cache.infer(Query.make(6,{'A','B'})) is None
    cache=FeasibilityCache();cache.add_exclusion(Query.make(2,{'A','B'},1),'k1')
    assert cache.infer(Query.make(6,{'A','B'},2)) is None
    print({'queries_checked':len(queries),'inference_directions':'passed'})

if __name__=='__main__':self_test()
