#!/usr/bin/env python3
"""Multi-template structural successor for Candidate A v1.2.

This is a development-only construction overlay.  It reuses the accepted V3
kernel, mechanisms, objectives and verifier while changing operational motif
structure before any solve.  A fixed manifest controls prospective runs.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

VERSION = "candidate_a_v12_multitemplate_structural_successor_v1"
EVIDENCE_SCOPE = "DEVELOPMENT_ONLY_NOT_FORMAL_CONFIRMATION_NOT_MODEL_EVIDENCE"
MOTIFS = (
    "BASE_SINGLE_RESOURCE",
    "THIRD_UAV_FEEDER",
    "THIRD_UAV_CHAIN",
    "THIRD_UAV_ROUTE_DIAMOND",
)
TOPOLOGIES = ("SHARED_ORIGIN_PAD_CAPACITY", "SHARED_DESTINATION_PAD_CAPACITY", "SHARED_CORRIDOR_CAPACITY")
TIME_SHIFTS = (0, 2, 4, 6, 1, 3, 5, 7)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_LOAD_FAILED:" + str(path))
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    return module


def load_runtime(repo: Path, suffix: str) -> tuple[Any, Any, dict[str, Any]]:
    calibration = load("multitemplate_calibration_"+suffix, repo/"scripts"/"integrated_repair_candidate_a_v12_shortcut_neutral_population_calibration_v1.py")
    bridge = calibration.load_bridge(repo, "multitemplate_bridge_"+suffix)
    return calibration, bridge, bridge.load_modules(repo)


def _new_ids(old: Any, cell: dict[str, Any], motif: str, index: int) -> tuple[str, str, str]:
    key = cell["cell_key"] + "|" + motif
    return old.opaque("U", key, index), old.opaque("M", key, index), old.opaque("V", key, index)


def _add_resource_defaults(instance: dict[str, Any], corridor_ids: list[str], nodes: list[str]) -> None:
    for cid in corridor_ids:
        instance["resources"]["corridor_capacity_by_slot_default"][cid] = 2
    known = {v["vertiport_id"] for v in instance["topology"]["vertiports"]}
    for node in nodes:
        if node not in known:
            instance["topology"]["vertiports"].append({"vertiport_id": node, "pad_capacity": 2, "charger_count": 2}); known.add(node)
        instance["resources"]["pad_capacity_by_slot_default"][node] = 2
        instance["resources"]["charger_capacity_by_slot_default"][node] = 2


def _add_third_uav(modules: dict[str, Any], cell: dict[str, Any], motif: str, variant: int, chain: bool, diamond: bool) -> None:
    old, core = modules["old"], modules["core"]
    instance = cell["instance"]
    target_type = cell["uav_type"]
    third_type = target_type if variant % 2 == 0 else ("multirotor_cargo_uav" if target_type.startswith("fixed_wing") else "fixed_wing_vtol_cargo_uav")
    shared = cell["coupling_resource"]["node"]
    corridor_ids = {c["corridor_id"] for c in instance["topology"]["corridors"]}
    if shared in corridor_ids:
        shared = next(m["origin_vertiport"] for m in instance["missions"] if m["uav_id"] == cell["mechanism_uav_id"])
    uav_id, mission_id, destination = _new_ids(old, cell, motif, 201)
    start = shared
    release = 15 + variant % 3
    direct_cid = old.opaque("C", cell["cell_key"]+"|"+motif, 201)
    direct_corridor, direct_path = old.corridor_for_slots(core, instance["scenario_id"], direct_cid, start, destination, 2, 1.0+0.05*(variant%4), third_type, 0.5)
    paths = [(direct_corridor, direct_path)]
    mission = old.make_mission(mission_id, uav_id, 0, start, destination, paths, release, release+7)
    extra_corridors: list[dict[str, Any]] = []
    extra_nodes: list[str] = []
    if diamond:
        mid = old.opaque("V", cell["cell_key"]+"|"+motif, 202)
        c1, _ = old.corridor_for_slots(core, instance["scenario_id"], old.opaque("C", cell["cell_key"]+"|"+motif, 202), start, mid, 1, 0.62, third_type, 0.5)
        c2, _ = old.corridor_for_slots(core, instance["scenario_id"], old.opaque("C", cell["cell_key"]+"|"+motif, 203), mid, destination, 1, 0.62, third_type, 0.5)
        seed = {"path_id": old.opaque("PATH", cell["cell_key"]+"|"+motif, 202), "corridor_ids": [c1["corridor_id"], c2["corridor_id"]], "node_sequence": [start, mid, destination]}
        diamond_path = core.path_metrics(seed, {c["corridor_id"]:c for c in (c1,c2)}, third_type, 0.5, instance["scenario_id"])
        mission["path_options"].append(diamond_path); extra_corridors.extend([c1,c2]); extra_nodes.append(mid)
    instance["fleet"].append(old.make_fleet_row(core, uav_id, third_type, start, core.UAV_TYPES[third_type]["reserve_kwh"]+6.0))
    instance["missions"].append(mission); instance["topology"]["corridors"].append(direct_corridor); instance["topology"]["corridors"].extend(extra_corridors)
    cell["baseline"]["decisions"].append({"mission_id":mission_id,"uav_id":uav_id,"held":False,"path_id":direct_path["path_id"],"depart_slot":release,"charge_blocks":0})
    nodes=[start,destination,*extra_nodes]; _add_resource_defaults(instance,[direct_cid,*[c["corridor_id"] for c in extra_corridors]],nodes)
    if chain:
        second_id=old.opaque("M",cell["cell_key"]+"|"+motif,204); second_node=old.opaque("V",cell["cell_key"]+"|"+motif,204)
        # make_mission fixes payload_kg=0.5.  Path energy must be generated at
        # that exact payload or the formal verifier correctly reports an
        # ENERGY_COEFFICIENT_MISMATCH for the second mission.
        c3,p3=old.corridor_for_slots(core,instance["scenario_id"],old.opaque("C",cell["cell_key"]+"|"+motif,204),destination,second_node,1,0.72+0.03*(variant%3),third_type,0.5)
        second_release=release+4
        second=old.make_mission(second_id,uav_id,1,destination,second_node,[(c3,p3)],second_release,second_release+6)
        instance["missions"].append(second); instance["topology"]["corridors"].append(c3)
        cell["baseline"]["decisions"].append({"mission_id":second_id,"uav_id":uav_id,"held":False,"path_id":p3["path_id"],"depart_slot":second_release,"charge_blocks":0})
        _add_resource_defaults(instance,[c3["corridor_id"]],[second_node])
    instance["horizon_slots"] = max(int(instance["horizon_slots"]), release+12)
    cell["third_uav_id"] = uav_id


def apply_motif(modules: dict[str, Any], cell: dict[str, Any], motif: str, variant: int) -> None:
    if motif not in MOTIFS: raise RuntimeError("UNKNOWN_OPERATIONAL_MOTIF")
    if motif == "THIRD_UAV_FEEDER":
        _add_third_uav(modules,cell,motif,variant,False,False)
    elif motif == "THIRD_UAV_CHAIN":
        _add_third_uav(modules,cell,motif,variant,True,False)
    elif motif == "THIRD_UAV_ROUTE_DIAMOND":
        _add_third_uav(modules,cell,motif,variant,False,True)
    cell["operational_motif_private"] = motif


def _secondary_collision(bridge: Any, modules: dict[str, Any], cell: dict[str, Any], uncoupled: dict[str, Any], motif: str) -> None:
    # Retained as a no-op extension point.  The first bounded exploration
    # showed that opportunistically searching for a second collision did not
    # define a stable motif; it is therefore excluded from the frozen library.
    return
    core=modules["core"]; plan=uncoupled["target_plan"]
    candidates=set(bridge.resource_keys_for_decision(core,cell,plan,cell["linked_mission_ids"][0])) & set(bridge.resource_keys_for_decision(core,cell,plan,cell["linked_mission_ids"][1]))
    primary=(cell["coupling_resource"]["node"],int(cell["coupling_resource"]["slot"]))
    corridor_ids={c["corridor_id"] for c in cell["instance"]["topology"]["corridors"]}
    options=[key for key in sorted(candidates) if key!=primary]
    if not options: raise RuntimeError("SECONDARY_SHARED_RESOURCE_COLLISION_NOT_FOUND")
    preferred=[key for key in options if (key[0] in corridor_ids)!=(primary[0] in corridor_ids)]
    node,slot=(preferred or options)[0]
    if node in corridor_ids:
        rows=cell["intervention"].setdefault("corridor_capacity_overrides",[]); idkey="corridor_id"
    else:
        rows=cell["intervention"].setdefault("pad_capacity_overrides",[]); idkey="vertiport_id"
    rows[:] = [r for r in rows if not (r.get(idkey)==node and int(r.get("slot",-1))==slot)]
    rows.append({idkey:node,"slot":int(slot),"capacity":1}); rows.sort(key=lambda r:(r[idkey],int(r["slot"])))
    cell["secondary_coupling_resource"]={"kind":"corridor" if node in corridor_ids else "pad","node":node,"slot":int(slot),"capacity":1}
    cell["intervention"].pop("intervention_sha256",None); cell["intervention"]["intervention_sha256"]=core.sha256_obj(cell["intervention"])


def build_multitemplate_cell(calibration: Any, bridge: Any, modules: dict[str, Any], attempt: dict[str, Any], physical_variant: int, identity_variant: int, original_build: Any) -> dict[str, Any]:
    cell=original_build(modules,attempt["mechanism"],attempt["objective_role"],attempt["target_uav_type"],physical_variant,attempt["coupling_topology"])
    apply_motif(modules,cell,attempt["operational_motif"],physical_variant)
    calibration._apply_label_independent_time_translation(bridge,cell,int(attempt["nuisance_profile"]))
    calibration._rehash_cell(bridge,modules,cell,attempt,identity_variant)
    return cell


def construct_candidate(calibration: Any, bridge: Any, modules: dict[str, Any], attempt: dict[str, Any], identity_variant: int, time_limit: float) -> dict[str, Any]:
    offset=identity_variant-int(attempt["variant_start"]); physical=int(attempt["physical_variant_start"])+offset
    original_build=bridge.build_coupled_cell; original_bind=bridge.bind_capacity_at_selected_collision
    def build_overlay(_mods:dict[str,Any],mechanism:str,role:str,target:str,variant:int,topology:str):
        if (mechanism,role,target,variant,topology)!=(attempt["mechanism"],attempt["objective_role"],attempt["target_uav_type"],physical,attempt["coupling_topology"]): raise RuntimeError("STRUCTURAL_COORDINATE_DRIFT")
        return build_multitemplate_cell(calibration,bridge,modules,attempt,physical,identity_variant,original_build)
    def bind_overlay(core:Any,cell:dict[str,Any],uncoupled:dict[str,Any],variant:int):
        original_bind(core,cell,uncoupled,variant); _secondary_collision(bridge,modules,cell,uncoupled,attempt["operational_motif"])
    bridge.build_coupled_cell=build_overlay; bridge.bind_capacity_at_selected_collision=bind_overlay
    try: result=bridge.construct_certificate(modules,attempt["mechanism"],attempt["objective_role"],attempt["target_uav_type"],physical,attempt["coupling_topology"],time_limit)
    finally: bridge.build_coupled_cell=original_build; bridge.bind_capacity_at_selected_collision=original_bind
    lineage={"attempt_id":attempt["attempt_id"],"attempt_rank":attempt["rank"],"ancestor_id":attempt["ancestor_id"],"operational_motif":attempt["operational_motif"],"nuisance_profile":attempt["nuisance_profile"],"physical_variant":physical,"candidate_offset":offset,"candidate_variant":identity_variant}
    result["private"]["structural_successor_lineage"]=lineage
    result["private"]["version"]=VERSION+"_private_certificate"
    result["private"]["certificate_sha256"]=sha_obj({k:v for k,v in result["private"].items() if k!="certificate_sha256"})
    result["public"]["version"]=VERSION+"_public_projection"
    result["public"]["public_projection_sha256"]=sha_obj({k:v for k,v in result["public"].items() if k!="public_projection_sha256"})
    result["summary"].update(lineage); result["summary"]["cell_id"]=result["private"]["cell"]["cell_id"]
    result["summary"]["certificate_sha256"]=result["private"]["certificate_sha256"]; result["summary"]["public_projection_sha256"]=result["public"]["public_projection_sha256"]
    result["summary"]["structural_template_sha256"]=result["private"]["instance"]["structural_signatures"]["template_sha256"]
    result["summary"]["coarse_structural_sha256"]=result["private"]["instance"]["structural_signatures"]["coarse_sha256"]
    result["summary"]["constraint_incidence_sha256"]=sha_obj({"motif":attempt["operational_motif"],"topology":attempt["coupling_topology"],"missions":[(m["uav_id"],m["sequence_index"],m["origin_vertiport"],m["destination_vertiport"],tuple(tuple(p["corridor_ids"]) for p in m["path_options"])) for m in result["private"]["instance"]["missions"]]})
    return result


def rejection(exc: Exception) -> str:
    msg=str(exc)
    for key in ("MECHANISM_PRESERVING_ALTERNATIVE_NOT_FOUND","SEMANTIC_ROUTE_SOC_INTERVAL_EMPTY","MIXED_L5_SOC_INTERVAL_EMPTY","SECONDARY_SHARED_RESOURCE_COLLISION_NOT_FOUND","meaningful_positive_gap"):
        if key in msg:return key
    return type(exc).__name__+":"+msg.split(":",1)[0]


def write_candidate(out: Path, result: dict[str,Any]) -> None:
    (out/"private").mkdir(parents=True,exist_ok=True); (out/"public").mkdir(parents=True,exist_ok=True); cid=result["summary"]["cell_id"]
    (out/"private"/(cid+".json")).write_text(json.dumps(result["private"],ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    (out/"public"/("PUB_"+cid+".json")).write_text(json.dumps(result["public"],ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")


def verify_manifest(manifest: dict[str,Any], expected: int|None) -> None:
    attempts=manifest["attempts"]
    if expected is not None and len(attempts)!=expected: raise RuntimeError("DENOMINATOR_MISMATCH")
    if [a["rank"] for a in attempts]!=list(range(1,len(attempts)+1)):raise RuntimeError("RANK_ORDER_MISMATCH")
    if len({a["attempt_id"] for a in attempts})!=len(attempts) or len({a["ancestor_id"] for a in attempts})!=len(attempts):raise RuntimeError("IDENTITY_DUPLICATE")
    if any(a["operational_motif"] not in MOTIFS for a in attempts):raise RuntimeError("MOTIF_INVALID")
    if manifest.get("manifest_sha256")!=sha_obj({k:v for k,v in manifest.items() if k!="manifest_sha256"}):raise RuntimeError("MANIFEST_DIGEST_MISMATCH")


def run(repo:Path,manifest_path:Path,out:Path,time_limit:float,exploration:bool) -> dict[str,Any]:
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")); verify_manifest(manifest,None if exploration else int(manifest["fixed_denominator"]))
    if out.exists() and any(out.iterdir()):raise RuntimeError("OUTPUT_NOT_EMPTY")
    out.mkdir(parents=True,exist_ok=True); calibration,bridge,modules=load_runtime(repo,"run"); started=time.perf_counter()
    outcomes=[]; candidates=[]; rejects=Counter()
    for attempt in manifest["attempts"]:
        row={**attempt,"attempt_status":"REJECTED_NO_ADMITTED_CANDIDATE","candidate_attempt_count":0,"candidate_rejections":[],"admitted_summary":None}
        for offset in range(int(attempt["opportunity_budget"])):
            variant=int(attempt["variant_start"])+offset; row["candidate_attempt_count"]+=1
            try:
                result=construct_candidate(calibration,bridge,modules,attempt,variant,time_limit); c={"rank":attempt["rank"],**result["summary"]}; candidates.append(c)
                if result["summary"]["admitted"]:
                    write_candidate(out,result); row["attempt_status"]="ADMITTED"; row["admitted_summary"]=result["summary"]; break
                reason="PREDICATE_FALSE"; rejects[reason]+=1; row["candidate_rejections"].append({"candidate_variant":variant,"reason":reason})
            except Exception as exc:
                reason=rejection(exc); rejects[reason]+=1; candidates.append({"rank":attempt["rank"],"candidate_variant":variant,"admitted":False,"reason":reason}); row["candidate_rejections"].append({"candidate_variant":variant,"reason":reason,"message":str(exc)})
        outcomes.append(row)
    admitted=[r["admitted_summary"] for r in outcomes if r["admitted_summary"] is not None]
    summary={"version":VERSION+"_summary","evidence_scope":EVIDENCE_SCOPE,"mode":"exploration" if exploration else "prospective_fixed_denominator","registered_attempt_count":len(outcomes),"completed_attempt_count":len(outcomes),"admitted_attempt_count":len(admitted),"rejected_attempt_count":len(outcomes)-len(admitted),"candidate_attempt_count":len(candidates),"production_subsolve_count":int(modules["solve_counter"]["subsolves"]),"wall_seconds":round(time.perf_counter()-started,6),"attempts":outcomes,"candidate_rows":candidates,"candidate_rejection_counts":dict(rejects),"cell_admitted_counts":{"|".join(k):v for k,v in Counter((x["mechanism"],x["objective_role"]) for x in admitted).items()},"motif_admitted_counts":dict(Counter(x["operational_motif"] for x in admitted)),"uav_admitted_counts":dict(Counter(x["target_uav_type"] for x in admitted)),"topology_admitted_counts":dict(Counter(x["coupling_topology"] for x in admitted)),"formal_confirmation_count":0,"formal_pool_count":0,"model_api_network_call_count":0,"secret_or_dotenv_read_count":0}
    (out/"ATTEMPT_OUTCOMES.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in outcomes),encoding="utf-8")
    (out/"POPULATION_SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"attempts":len(outcomes),"admitted":len(admitted),"candidates":len(candidates),"subsolves":summary["production_subsolve_count"],"wall":summary["wall_seconds"]},sort_keys=True)); return summary


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--repo",required=True);ap.add_argument("--manifest",required=True);ap.add_argument("--output",required=True);ap.add_argument("--time-limit",type=float,default=20);ap.add_argument("--exploration",action="store_true")
    a=ap.parse_args();run(Path(a.repo).resolve(),Path(a.manifest).resolve(),Path(a.output).resolve(),a.time_limit,a.exploration);return 0


if __name__=="__main__":raise SystemExit(main())
