"""Connect stored Core task diagnostics to actual candidates; no solves or API calls.
Run from any directory with Python. Only stage analysis/ files are written.
Replays 18 stored witnesses and 432 stored selector outcomes without regeneration.
"""
from pathlib import Path
from collections import Counter
import ast, csv, json, sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
W=ROOT.parent
P=W.parent
R=W/"arco_codex_research_20260925"
S=W/"arco_codex_research_20260930"
C=W/"arco_closing_study/core_r4"
OUT=ROOT/"analysis"
TIERS=("urgent_holds","total_holds","repair_distance","weighted_tardiness_min","delay_and_charge_wait_min","energy_kwh")
MODELS={"deepseek_complete":"DeepSeek","luna_complete":"Luna"}
def read(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def jl(p): return [json.loads(s) for s in p.read_text(encoding="utf-8-sig").splitlines() if s.strip()]
def cr(p): return list(csv.DictReader(p.open(encoding="utf-8-sig")))
def rel(p): return __import__('os').path.relpath(p,W).replace('\\','/')
def write(name,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (OUT/name).open("w",encoding="utf-8-sig",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=fields);wr.writeheader()
        wr.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict,tuple)) else v for k,v in row.items()} for row in rows)
def rq(obj,ref): return bool(obj) and all(abs(obj[k]-ref[k])<=(1e-4 if i==5 else 0) for i,k in enumerate(TIERS))
def first(obj,ref):
    for i,k in enumerate(TIERS):
        gap=obj[k]-ref[k]
        if abs(gap)>(1e-4 if i==5 else 0): return "L"+str(i+1),gap
    return None,None
def diff(a,b):
    aa={d["mission_id"]:d for d in a};bb={d["mission_id"]:d for d in b};assert aa.keys()==bb.keys()
    keys=("held","path_id","depart_slot","charge_blocks")
    return [m for m in aa if any(aa[m][k]!=bb[m][k] for k in keys)]
def plans(p): return {r["record_id"]:json.loads(r["raw_text"])["decisions"] for r in jl(p)}
def main():
    OUT.mkdir(exist_ok=True)
    tasks={p.stem:read(p) for p in sorted((P/"data/public/records").glob("CA12_CORE_*.json"))}
    priv={rid:read(P/"data/private/evaluator_records"/(rid+".json")) for rid in tasks}
    refs={r["record_id"]:r for r in jl(P/"references/public_domain.jsonl")}
    master={(r["record_id"],r["source"]):r for r in jl(P/"results/current/MASTER.jsonl") if r["source"] in MODELS}
    coord={r["task"]:r for r in read(S/"coordination/results.json")}
    recomputed={r["record_id"]:r for r in jl(P/"evidence/reference_recomputation.jsonl")}
    witnesses={r["record_id"]:r for r in jl(S/"coordination/nearest_quality.jsonl")}
    cap={r["task"]:r for r in read(S/"capacity/results.json")}
    oldcap={r["record_id"]:r for r in cr(P/"results/current/Supplement_capacity_counterfactuals.csv")}
    restrictions=jl(R/"certificate_relations/construction_counterfactuals.source.jsonl")
    actionq={(r["record_id"],r["restriction"]):r for r in read(R/"certificate_relations/action_quality.json")}
    domains=read(R/"certificate_relations/domain_feasibility.json")
    four={r["record_id"]:r for r in read(R/"certificate_relations/four_route_cases.json")}
    sels=read(R/"policy_domains/selection.json")["tasks"]
    gs={r["record_id"]:r for r in sels if r["policy"]=="public" and r["model"]=="deepseek_complete"}
    g=plans(R/"policy_domains/public_both.jsonl")
    r3={r["record_id"]:r for r in read(R/"local_repair/results.json")}
    r4={r["record_id"]:r for r in read(C/"results.json")}
    modelplans={}
    for src in MODELS:
        modelplans[src]={r["record_id"]:json.loads(r["raw_text"])["decisions"] for r in jl(P/"responses"/(src+".jsonl")) if master[r["record_id"],src]["schema"]}
    selector=P/"vendor/scripts/run_candidate_a_v12p1_verifier_gated_portfolio_v1.py"
    node=next(n for n in ast.parse(selector.read_text(encoding="utf-8")).body if isinstance(n,ast.FunctionDef) and n.name=="lex_compare")
    scope={"TIERS":TIERS,"ENERGY_TOL":1e-4}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(selector),"exec"),scope)
    compare=scope["lex_compare"]
    sys.path.insert(0,str(P))
    import admit
    rt=admit.public_runtime()
    def verify(rid,ds):
        return admit.admit([{"record_id":rid,"raw_text":json.dumps({"record_id":rid,"decisions":ds})}],rt)[0]
    verified={rid:verify(rid,r["decisions"]) for rid,r in witnesses.items()}
    fourverified={rid:verify(rid,r["public_decisions"]) for rid,r in four.items()}
    rows=[];lookup={}
    for rid,t in tasks.items():
        mm={m["mission_id"]:m for m in t["instance"]["missions"]}
        base={d["mission_id"]:d for d in t["baseline"]["decisions"]}
        inv={v:k for k,v in priv[rid]["public_to_internal_id"].items()}
        soc=priv[rid]["selected_pair"]["soc"];u=inv[soc["uav_id"]];target=inv[soc["soc_target_mission_id"]]
        pre=[m for m in mm if mm[m]["uav_id"]==u and mm[m]["sequence_index"]<mm[target]["sequence_index"]]
        route=priv[rid]["selected_pair"].get("route");route_mid=inv[route["mission_id"]] if route else None
        for source in ("G","R3","R4","DeepSeek","Luna"):
            if source=="G":
                ds=g[rid];obj=gs[rid]["policy_objective"];valid=gs[rid]["policy_admissible"];quality=gs[rid]["policy_quality"];errors=[]
                outcome="reference_quality_repair" if quality else "admissible_reference_miss";origin=R/"policy_domains/public_both.jsonl"
            elif source in ("R3","R4"):
                item=(r3 if source=="R3" else r4)[rid]
                ds=item["decisions"];obj=item["objective"];valid=item["admissible"];quality=item["reference_quality"];errors=[]
                outcome="reference_quality_repair" if quality else "admissible_reference_miss"
                origin=R/"local_repair/results.json" if source=="R3" else C/"results.json"
            else:
                src=next(k for k,v in MODELS.items() if v==source);item=master[rid,src]
                ds=modelplans[src].get(rid);obj=item["objective"];valid=item["schema"] and item["formal"]
                quality=item["reference_quality"];errors=item["formal_errors"];outcome=item["category"];origin=P/"responses"/(src+".jsonl")
            loss,gap=first(obj,refs[rid]["objective"]) if valid else (None,None)
            assert not valid or rq(obj,refs[rid]["objective"])==quality
            row=dict(record_id=rid,source=source,outcome=outcome,admissible=valid,reference_quality=quality,
                     full_service=valid and obj["total_holds"]==0,first_loss=loss,first_loss_gap=gap,
                     formal_errors=errors,is_R3_distance_case=rid in coord,is_route_domain_case=rid in four,
                     capacity_global_first_change=cap[rid]["first_changed_layer"],
                     capacity_designated_gap_changed=cap[rid]["designated_gap_changed"],
                     objective=obj,reference=refs[rid]["objective"],candidate_source=rel(origin))
            if valid:
                dd={d["mission_id"]:d for d in ds};changes=diff(g[rid],ds)
                row.update(mission_changes_from_G=len(changes),changed_missions_from_G=changes,
                           changed_uavs_from_G=sorted({dd[m]["uav_id"] for m in changes}),
                           pretarget_charge_changed=any(dd[m]["charge_blocks"]!=base[m]["charge_blocks"] for m in pre),
                           pretarget_charge_signed_delta=sum(dd[m]["charge_blocks"]-base[m]["charge_blocks"] for m in pre),
                           target_uav_route_changed=any(dd[m]["path_id"]!=base[m]["path_id"] for m in mm if mm[m]["uav_id"]==u and not dd[m]["held"]),
                           target_uav_departure_changed=any(dd[m]["depart_slot"]!=base[m]["depart_slot"] for m in mm if mm[m]["uav_id"]==u and not dd[m]["held"]),
                           designated_route_mission=route_mid,
                           designated_route_changed=(dd[route_mid]["path_id"]!=base[route_mid]["path_id"]) if route_mid and not dd[route_mid]["held"] else None,
                           exact_reference_decisions=not diff(refs[rid]["decisions"],ds))
            rows.append(row);lookup[rid,source]=row
    assert len(rows)==360
    write("core_candidate_diagnostics.csv",rows)
    rest=[]
    flags={"charge_disabled":"pretarget_charge_changed","routes_fixed":"target_uav_route_changed","route_disabled":"designated_route_changed","departures_fixed":"target_uav_departure_changed"}
    for r in restrictions:
        rid,k=r["record_id"],r["kind"];feasible=r["classification"]=="FEASIBLE"
        assert r["solver_status"]==(0 if feasible else 2)
        qual=(k=="full" or actionq[rid,k]["reference_quality_feasible"]) if feasible else False
        row=dict(record_id=rid,restriction=k,stored_classification=r["classification"],stored_solver_status=r["solver_status"],
                 old_construction_classification=r["old_classification"],public_full_service_feasible=feasible,public_reference_quality_feasible=qual,
                 source=rel(R/"certificate_relations/construction_counterfactuals.source.jsonl"))
        for model in MODELS.values():
            c=lookup[rid,model];row[model+"_outcome"]=c["outcome"];row[model+"_reference_quality"]=c["reference_quality"]
            row[model+"_excluded_action_observed"]=c.get(flags.get(k,"")) if c["full_service"] and k!="full" else None
            if k!="full" and c["full_service"] and (not feasible or (not qual and c["reference_quality"])):
                assert row[model+"_excluded_action_observed"],(rid,k,model)
        rest.append(row)
    assert len(rest)==248
    write("core_action_restrictions.csv",rest)
    drows=[]
    for rid,c in coord.items():
        chain=Counter(m["uav_id"] for m in tasks[rid]["instance"]["missions"])
        ds=witnesses[rid]["decisions"];changes=diff(g[rid],ds);uavs=sorted({d["uav_id"] for d in ds if d["mission_id"] in changes})
        v=verified[rid];assert v["admissible"] and rq(v["objective_vector"],refs[rid]["objective"])
        assert len(changes)==c["k_star"]==c["distance_lower_bound"]==4 and c["mip_gap"]==0
        assert max(chain.values())==3 and len(uavs)==2
        row=dict(record_id=rid,distance_origin="G/public_both",fixed_chain_membership=True,
                 chain_missions=dict(sorted(chain.items())),max_chain_missions=max(chain.values()),
                 stored_distance_lower_bound=c["distance_lower_bound"],stored_k_star=c["k_star"],stored_mip_gap=c["mip_gap"],
                 witness_changed_missions=changes,witness_changed_mission_count=len(changes),witness_changed_uavs=uavs,
                 witness_quality_replayed=True,witness_admissible_replayed=v["admissible"],
                 minimum_changed_chains_lower_bound=2,minimum_changed_chains_upper_bound=len(uavs),
                 bound_argument="Any reference-quality plan changes at least four missions from G; each fixed chain has at most three. The verified two-chain witness closes the bound.",
                 task_source=rel(P/"data/public/records"/(rid+".json")),distance_source=rel(S/"coordination/results.json"),
                 witness_source=rel(S/"coordination/nearest_quality.jsonl"),G_source=rel(R/"policy_domains/public_both.jsonl"))
        for src in ("G","R3","R4","DeepSeek","Luna"):
            for key in ("reference_quality","first_loss","first_loss_gap","mission_changes_from_G","changed_uavs_from_G","objective"):
                row[src+"_"+key]=lookup[rid,src].get(key)
        drows.append(row)
    write("core_distance_candidates.csv",drows)
    frows=[]
    for rid,r in four.items():
        row=dict(record_id=rid,horizon_slot=r["horizon"],restricted_L3=r["restricted_L3"],reference_L3=r["reference_L3"],L3_excess=r["L3_excess"],
                 late_completion_events=r["late_events"],public_all_served_witness_replayed=fourverified[rid]["admissible"],
                 restricted_quality=rq(fourverified[rid]["objective_vector"],refs[rid]["objective"]),source=rel(R/"certificate_relations/four_route_cases.json"))
        for d in domains:
            if d["record_id"]==rid:
                prefix=d["domain"]+("_route_fixed" if d["route_restricted"] else "_unrestricted")
                row[prefix+"_full_service"]=d["all_served_feasible"];row[prefix+"_solver_status"]=d["solver_status"]
        for model in MODELS.values():
            row[model+"_outcome"]=lookup[rid,model]["outcome"];row[model+"_designated_route_changed"]=lookup[rid,model]["designated_route_changed"]
        assert row["public_all_served_witness_replayed"] and not row["restricted_quality"] and r["L3_excess"]==27
        frows.append(row)
    write("core_route_domain_cases.csv",frows)
    crows=[]
    for rid,c in cap.items():
        row=dict(record_id=rid,global_first_changed_layer=c["first_changed_layer"],global_objective_changed=c["first_changed_layer"] is not None,
                 selected_public_optimum_decisions_changed=c["selected_optimum_decisions_changed"],
                 relaxed_optimum_valid_under_original_capacity=c["relaxed_optimum_valid_under_original_capacity"],
                 designated_gap_changed=c["designated_gap_changed"],coupled_gap=c["coupled_gap"],relaxed_gap=c["relaxed_gap"],gap_tier=c["gap_tier"],
                 base_objective=c["base_objective"],relaxed_objective=c["relaxed_objective"],source=rel(S/"capacity/results.json"))
        for k in ("target_decisions_changed","competitor_decisions_changed","resource_order_changed","capacity_rejects_at_least_one"):
            row["construction_"+k]=oldcap[rid][k]=="True"
        for model in MODELS.values():
            row[model+"_outcome"]=lookup[rid,model]["outcome"];row[model+"_reference_quality"]=lookup[rid,model]["reference_quality"]
        crows.append(row)
    write("core_capacity_diagnostics.csv",crows)
    srows=[]
    for det,old in (("G","public"),("R3","local_repair")):
        for s in sels:
            if s["policy"]!=old:continue
            rid=s["record_id"];model=MODELS[s["model"]];d,m=lookup[rid,det],lookup[rid,model]
            take_d=not m["admissible"] or compare(d["objective"],m["objective"])<=0
            chosen=det if take_d else model
            assert (s["selected"]=="policy")==take_d and s["selected_quality"]==lookup[rid,chosen]["reference_quality"]
            srows.append(dict(record_id=rid,pair=det+"+"+model,selected_source=chosen,selected_quality=s["selected_quality"],
                              model_only_quality=m["reference_quality"] and not d["reference_quality"],model_selected=chosen==model,
                              stored_selection_replayed=True,source=rel(R/"policy_domains/selection.json")))
    for s in cr(C/"selection.csv"):
        rid=s["record_id"];model="DeepSeek" if s["pair"].endswith("deepseek") else "Luna";m,d=lookup[rid,model],lookup[rid,"R4"]
        take_d=not m["admissible"] or compare(d["objective"],m["objective"])<=0;chosen="R4" if take_d else model
        assert (s["selected"]=="R4")==take_d and (s["selected_quality"]=="True")==lookup[rid,chosen]["reference_quality"]
        srows.append(dict(record_id=rid,pair="R4+"+model,selected_source=chosen,selected_quality=s["selected_quality"]=="True",
                          model_only_quality=m["reference_quality"] and not d["reference_quality"],model_selected=chosen==model,
                          stored_selection_replayed=True,source=rel(C/"selection.csv")))
    write("core_selector_links.csv",srows)
    design=[]
    for rid,r in recomputed.items():
        c=r["competitor_check"];role=priv[rid]["metadata"]["objective_role"];tier=int(role[1]);key=TIERS[tier-1]
        prefix=all(abs(c["target_vector"][k]-c["competitor_vector"][k])<=1e-6 for k in TIERS[:tier-1])
        threshold=.05 if tier==6 else 5
        retained=bool(c["formal_valid"] and c["status"]==0 and prefix and c["gap"]>=threshold-1e-6)
        assert retained and r["unchanged_under_scoring_tolerance"]
        design.append(dict(record_id=rid,designated_tier="L"+str(tier),design_role=role,public_reference_matches_construction=r["unchanged_under_scoring_tolerance"],
                           public_competitor_feasible=c["formal_valid"],public_competitor_status=c["status"],public_equal_earlier_prefix=prefix,
                           public_designated_gap=c["gap"],gap_unit="kWh" if tier==6 else "weighted minutes" if tier==4 else "minutes",
                           public_design_relation_retained=retained,construction_mechanism=r["mechanism_selected_old"],
                           public_service_necessity_mechanism=r["mechanism_selected_new"],
                           source=rel(P/"evidence/reference_recomputation.jsonl")))
    write("core_design_relations.csv",design)
    summary={
      "scope":dict(tasks=72,candidate_rows=len(rows),restriction_rows=len(rest),distance_cases=len(coord),route_domain_cases=len(four),
                   witness_verifier_replays=18,selector_record_replays=len(srows),new_solves=0,api_calls=0),
      "design_relations":dict(tasks=len(design),public_relations_retained=sum(r["public_design_relation_retained"] for r in design),
                              designated_tiers=dict(Counter(r["designated_tier"] for r in design)),
                              public_service_necessity_label_changed=[r["record_id"] for r in design if r["construction_mechanism"]!=r["public_service_necessity_mechanism"]]),
      "candidate_outcomes":{s:dict(Counter(r["outcome"] for r in rows if r["source"]==s)) for s in ("G","R3","R4","DeepSeek","Luna")},
      "restriction_counts":{k:dict(Counter("full_service_infeasible" if not r["public_full_service_feasible"] else "reference_quality_feasible" if r["public_reference_quality_feasible"] else "full_service_only" for r in rest if r["restriction"]==k)) for k in sorted({r["restriction"] for r in rest})},
      "distance_candidates":{s:dict(quality=sum(lookup[rid,s]["reference_quality"] for rid in coord),
                                    first_losses=dict(Counter(lookup[rid,s]["first_loss"] or "quality" for rid in coord)),
                                    mission_change_distribution_from_G=dict(Counter(lookup[rid,s]["mission_changes_from_G"] for rid in coord))) for s in ("G","R3","R4","DeepSeek","Luna")},
      "distance_chain_conclusion":dict(minimum_changed_chains=2,covered_cases=14,premises="Relative to G, fixed chains, k*=4, maximum chain length 3, verified two-chain reference-quality witness."),
      "capacity_cross":[dict(global_first_changed_layer=k[0],designated_gap_changed=k[1],tasks=v) for k,v in Counter((r["global_first_changed_layer"],r["designated_gap_changed"]) for r in crows).items()],
      "capacity_event_counts":{k:sum(r[k] for r in crows) for k in ("global_objective_changed","selected_public_optimum_decisions_changed","construction_target_decisions_changed","construction_competitor_decisions_changed","construction_resource_order_changed","construction_capacity_rejects_at_least_one","designated_gap_changed")},
      "capacity_event_set_disagreements_with_global":{k:sum(r[k]!=r["global_objective_changed"] for r in crows) for k in ("construction_target_decisions_changed","construction_competitor_decisions_changed","construction_resource_order_changed","designated_gap_changed")},
      "selector_summary":{p:dict(selected_quality=sum(r["selected_quality"] for r in srows if r["pair"]==p),model_selected=sum(r["model_selected"] for r in srows if r["pair"]==p),model_only_quality=sum(r["model_only_quality"] for r in srows if r["pair"]==p)) for p in sorted({r["pair"] for r in srows})},
      "model_nonquality":[{k:r[k] for k in ("record_id","source","outcome","first_loss","first_loss_gap","formal_errors","objective","reference")} for r in rows if r["source"] in MODELS.values() and not r["reference_quality"]],
      "quality_plans_differing_from_stored_reference":{s:sum(r["reference_quality"] and not r.get("exact_reference_decisions",False) for r in rows if r["source"]==s) for s in MODELS.values()}
    }
    (OUT/"core_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

