#!/usr/bin/env python3
"""Strict parser, formal scorer, and aggregate reporter for the curated track."""
from __future__ import annotations
import argparse, importlib.util, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

OBJ=("urgent_holds","total_holds","repair_distance","weighted_tardiness_min","delay_and_charge_wait_min","energy_kwh")
ENERGY_EQUALITY_TOLERANCE=1e-4
ROOT_KEYS={"record_id","decisions"};DECISION_KEYS={"mission_id","uav_id","held","path_id","depart_slot","charge_blocks"}

def load(name:str,path:Path)->Any:
 spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
def read(p:Path)->Any:return json.loads(p.read_text(encoding="utf-8"))
def wilson(k:int,n:int,z:float=1.959963984540054)->list[float|None]:
 if not n:return [None,None]
 p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [max(0,c-h),min(1,c+h)]
def metric(rows:list[dict[str,Any]],key:str)->dict[str,Any]:
 k=sum(bool(x[key]) for x in rows);n=len(rows);return {"numerator":k,"denominator":n,"rate":k/n if n else None,"wilson95":wilson(k,n)}

def parse(raw_text:str,record_id:str,private:dict[str,Any])->tuple[dict[str,Any]|None,list[str]]:
 errors=[]
 try:value=json.loads(raw_text)
 except Exception as exc:return None,["INVALID_JSON:"+type(exc).__name__]
 if not isinstance(value,dict):return None,["ROOT_NOT_OBJECT"]
 if set(value)!=ROOT_KEYS:errors.append("ROOT_FIELDS_MISMATCH")
 if value.get("record_id")!=record_id:errors.append("RECORD_ID_MISMATCH")
 decisions=value.get("decisions")
 if not isinstance(decisions,list):return None,errors+["DECISIONS_NOT_ARRAY"]
 instance=private["instance"];missions={m["mission_id"]:m for m in instance["missions"]};reverse=private["public_to_internal_id"];mapped=[];seen=set()
 for pos,row in enumerate(decisions):
  prefix=f"DECISION_{pos}:"
  if not isinstance(row,dict):errors.append(prefix+"NOT_OBJECT");continue
  if set(row)!=DECISION_KEYS:errors.append(prefix+"FIELDS_MISMATCH");continue
  pmid=row.get("mission_id");puid=row.get("uav_id");ppath=row.get("path_id")
  if not isinstance(pmid,str) or pmid not in reverse:errors.append(prefix+"MISSION_ID_INVALID");continue
  mid=reverse[pmid]
  if mid not in missions:errors.append(prefix+"MISSION_ID_UNKNOWN");continue
  if mid in seen:errors.append(prefix+"MISSION_DUPLICATE");continue
  seen.add(mid);mission=missions[mid]
  if not isinstance(puid,str) or reverse.get(puid)!=mission["uav_id"]:errors.append(prefix+"UAV_ID_INVALID")
  held=row.get("held");charge=row.get("charge_blocks");depart=row.get("depart_slot")
  if type(held) is not bool:errors.append(prefix+"HELD_NOT_BOOLEAN");continue
  if type(charge) is not int or not 0<=charge<=int(instance["max_charge_blocks"]):errors.append(prefix+"CHARGE_BLOCKS_INVALID")
  if held:
   if ppath is not None or depart is not None or charge!=0:errors.append(prefix+"HELD_FIELDS_INVALID")
   path=None;departure=None
  else:
   allowed={p["path_id"] for p in mission["path_options"]}
   path=reverse.get(ppath) if isinstance(ppath,str) else None
   if path not in allowed:errors.append(prefix+"PATH_ID_INVALID")
   if type(depart) is not int or not 0<=depart<int(instance["horizon_slots"]):errors.append(prefix+"DEPART_SLOT_INVALID")
   departure=depart
  mapped.append({"mission_id":mid,"uav_id":mission["uav_id"],"held":held,"path_id":path,"depart_slot":departure,"charge_blocks":charge})
 if seen!=set(missions):errors.append("MISSION_COVERAGE_MISMATCH")
 if len(decisions)!=len(missions):errors.append("DECISION_COUNT_MISMATCH")
 return ({"record_id":record_id,"decisions":mapped} if not errors else None),errors

def score_one(record_id:str,raw_text:str,private:dict[str,Any],core:Any,formal:Any,bridge:Any,modules:dict[str,Any])->dict[str,Any]:
 parsed,errors=parse(raw_text,record_id,private);meta=private["metadata"]
 base={"record_id":record_id,"subset":private["subset"],**meta,"parse_valid":not errors,"schema_valid":not errors,"parse_errors":errors,"formal_feasible":False,"required_repair_semantics":False,"oracle_equivalent":False,"strict_success":False,"objective_vector":None,"lexicographic_first_difference":None,"first_difference_gap":None,"selected_reference_side":"NONE","formal_error_codes":[]}
 if parsed is None:return {**base,"failure_class":"PARSE_OR_SCHEMA_INVALID"}
 plan=core.make_plan(private["instance"],private["intervention"],"model_single_shot_submission",parsed["decisions"])
 evaluated=formal.evaluate_submission(private["instance"],private["intervention"],plan,baseline=private["baseline"],oracle=private["oracle_target_plan"])
 base["formal_feasible"]=bool(evaluated["valid"]);base["formal_error_codes"]=[e["code"] for e in evaluated.get("errors",[])];base["objective_vector"]=evaluated.get("objective")
 cell={"instance":private["instance"],"intervention":private["intervention"],"baseline":private["baseline"],"pair":private["selected_pair"],"mechanism":meta["mechanism"]}
 try:action=bridge.mechanism_action_evidence(modules,cell,parsed["decisions"]);base["required_repair_semantics"]=action["classification"]=="TRUE";base["mechanism_action_evidence"]=action
 except Exception as exc:base["mechanism_action_evidence"]={"error":type(exc).__name__+":"+str(exc)}
 target={x["name"]:float(x["value"]) for x in private["oracle_target_plan"]["objective_vector"]}
 competitor=formal.evaluate_submission(private["instance"],private["intervention"],private["oracle_competitor_plan"],baseline=private["baseline"],oracle=None).get("objective")
 obj=evaluated.get("objective") or {}
 if obj:
  def unequal(name:str,a:float,b:float)->bool:return abs(a-b)>ENERGY_EQUALITY_TOLERANCE if name=="energy_kwh" else a!=b
  first=next((name for name in OBJ if unequal(name,float(obj[name]),target[name])),None);base["lexicographic_first_difference"]=first;base["first_difference_gap"]=float(obj[first])-target[first] if first else 0.0
  base["oracle_equivalent"]=first is None
  if first is None:base["selected_reference_side"]="TARGET_EQUIVALENT"
  elif competitor and all(not unequal(k,float(obj[k]),float(competitor[k])) for k in OBJ):base["selected_reference_side"]="COMPETITOR_EQUIVALENT"
 base["strict_success"]=bool(base["formal_feasible"] and base["required_repair_semantics"] and base["oracle_equivalent"])
 if base["strict_success"]:failure="SUCCESS"
 elif not base["formal_feasible"]:failure="FORMAL_INFEASIBLE"
 elif not base["required_repair_semantics"]:failure="REQUIRED_SEMANTICS_MISSING"
 else:failure="FEASIBLE_SEMANTIC_BUT_LEXICOGRAPHICALLY_SUBOPTIMAL"
 return {**base,"failure_class":failure}

def aggregate(rows:list[dict[str,Any]])->dict[str,Any]:
 def summarize(ss:list[dict[str,Any]])->dict[str,Any]:return {"count":len(ss),"parse_schema_valid":metric(ss,"schema_valid"),"formal_feasible":metric(ss,"formal_feasible"),"required_repair_semantics":metric(ss,"required_repair_semantics"),"oracle_equivalent":metric(ss,"oracle_equivalent"),"strict_success":metric(ss,"strict_success"),"failure_taxonomy":dict(Counter(x["failure_class"] for x in ss)),"first_difference":dict(Counter(str(x["lexicographic_first_difference"]) for x in ss))}
 out={"overall":summarize(rows),"core72":summarize([x for x in rows if x["subset"]=="CORE"]),"extension14":summarize([x for x in rows if x["subset"]=="EXTENSION"]),"slices":{}}
 for key in ("mechanism","objective_role","target_uav_type","operational_motif","coupling_topology","coarse_structural_sha256"):
  out["slices"][key]={value:summarize([x for x in rows if x[key]==value]) for value in sorted({x[key] for x in rows})}
 out["paired_model_comparison_protocol"]={"primary":"paired difference in Core-72 strict-success rate","bootstrap":"10000 record-level paired bootstrap replicates, seed 20260802; additionally report objective-role-stratified paired bootstrap with 24 draws per role","interval":"two-sided percentile 95% CI","tests":"McNemar exact test for discordant strict-success pairs may be secondary","multiplicity":"slice intervals descriptive; no per-cell ranking claims for sparse cells"}
 return out

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument("--repo",required=True);ap.add_argument("--phase",required=True);ap.add_argument("--responses",required=True);ap.add_argument("--output",required=True);ap.add_argument("--require-count",type=int);ap.add_argument("--evidence-scope",choices=["MODEL_EVALUATION","OFFLINE_SMOKE_ONLY"],default="MODEL_EVALUATION");a=ap.parse_args();repo=Path(a.repo).resolve();phase=Path(a.phase).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
 runner=load("curated_score_runner",repo/"scripts"/"integrated_repair_candidate_a_v12_multitemplate_structural_successor_v1.py");cal,bridge,modules=runner.load_runtime(repo,"curated_model_scoring");core=modules["core"];formal=modules["formal"]
 responses=[]
 for line in Path(a.responses).read_text(encoding="utf-8").splitlines():
  if line.strip():responses.append(json.loads(line))
 if a.require_count is not None and len(responses)!=a.require_count:raise RuntimeError("RESPONSE_COUNT_MISMATCH")
 if len({x.get("record_id") for x in responses})!=len(responses):raise RuntimeError("DUPLICATE_RESPONSE_RECORD")
 rows=[]
 for response in responses:
  rid=response.get("record_id");p=phase/"private/evaluator_records"/(str(rid)+".json")
  if not p.exists():raise RuntimeError("UNKNOWN_RECORD_ID:"+str(rid))
  raw=response.get("raw_text");raw=raw if isinstance(raw,str) else ""
  rows.append(score_one(rid,raw,read(p),core,formal,bridge,modules))
 (out/"SCORED_RECORDS.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in rows),encoding="utf-8")
 report={"version":"candidate_a_v12_curated_repair_track_scoring_v1","evidence_scope":a.evidence_scope,"response_count":len(rows),"aggregate":aggregate(rows),"scoring_contract":{"primary_set":"Core-72","primary_metric":"strict_success","strict_success":"parse/schema valid AND formal feasible AND required repair semantics AND objective-vector oracle equivalence","objective_equivalence":"tiers L1-L5 exact; L6 energy_kwh absolute tolerance 1e-4 kWh","semantic_equivalent_action_encodings":"accepted when formal objective and mechanism semantics match; action-string equality is not required","no_json_repair":True,"no_verifier_feedback_regeneration":True}}
 (out/"AGGREGATE_REPORT.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8");print(json.dumps({"responses":len(rows),"strict":sum(x["strict_success"] for x in rows),"feasible":sum(x["formal_feasible"] for x in rows),"output":str(out)},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
