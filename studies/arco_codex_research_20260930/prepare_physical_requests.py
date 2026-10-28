"""Complete, provider-neutral message inputs; no endpoint clients or model results."""
from common import HERE,P,read,write

def main():
    original=(P/'prompts/complete_public_instructions.md').read_text(encoding='utf-8')
    start=original.index('These durations are constructed as')
    end=original.index('For service departure d',start)
    timing='''Segment duration is derived from the synthetic corridor geometry and the single instrumented M100 parameter model. Cruise time is 1000 * corridor.distance_km / cruise_speed_m_s seconds. Add cruise_altitude_m / takeoff_speed_m_s to the first segment, and cruise_altitude_m / landing_speed_m_s to the last segment. Take the ceiling of each resulting segment time divided by 300 seconds. The supplied edge_segments and travel_slots give these reserved occupancy intervals. travel_time_min_unrounded stores total continuous flight time including takeoff and landing. Rounding padding reserves the resource; flight energy uses continuous time. All winds are zero in these scenarios. Keep the supplied geometry, durations and parameter model unchanged.

'''
    instructions=(original[:start]+timing+original[end:]).replace('All supplied Core-72 incoming paths are absent','All supplied paired-scenario incoming paths are absent')
    start=instructions.index('Reconstruct flight energy as')
    end=instructions.index('## Six ordered objectives',start)
    energy='''Reconstruct flight energy using physical_parameters on the assigned UAV. Let m = airframe_instrumented_mass_kg + payload_kg, A = rotors * pi * (rotor_diameter_m/2)^2 and Pi = (m*g_m_s2)^1.5 / sqrt(2*air_density_kg_m3*A). For each of takeoff, cruise and landing, P_r = b1_r * Pi + b0_r watts, using power_coefficients. Their times in seconds are altitude/takeoff_speed, total geometric distance in meters/cruise_speed and altitude/landing_speed. E = sum(P_r*time_r) / 3600000 kWh. Use payload zero for incoming flights. Path energy fields retain full precision. The flight reserve is checked before post-service charging. Each five-minute block stores charger_input_power_w * charging_efficiency * (5/60)/1000 kWh; maximum charging is 15 minutes. Waiting and turnaround on the ground consume no flight energy. Use 1e-6 kWh tolerance at SOC bounds. These physical-layer rules replace the legacy distance-rate fields, which are unused in this task version.

'''
    instructions=instructions[:start]+energy+instructions[end:]
    out=HERE/'physical/next_model_inputs'; out.mkdir(exist_ok=True); (out/'complete_public_instructions.md').write_text(instructions,encoding='utf-8')
    import json
    system=(P/'prompts/system.txt').read_text(encoding='utf-8').strip()
    manifest=[]
    for path in sorted((HERE/'physical/tasks').glob('ARCO_PHYS_*.json')):
        task=read(path); user=instructions+'\n\nPublic task:\n\n'+json.dumps(task,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        for model in ('DeepSeek V4-Pro','GPT-5.6 Luna'):
            write(out/model.replace(' ','_')/(path.stem+'.json'),{'model_label':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}]})
        manifest.append({'record_id':task['record_id'],'public_task':str(path.relative_to(HERE)),'models':['DeepSeek V4-Pro','GPT-5.6 Luna'],'generations_per_model':1})
    write(out/'plan.json',{'status':'inputs_prepared','online_calls':0,'generation_budget':24,'model_labels':['DeepSeek V4-Pro','GPT-5.6 Luna'],'per_model_tasks':12,'output_token_cap':128000,'rules':'One generation per task; no quality retries or repair; freeze raw responses and use the physical-layer verifier; provider bindings and billing budget to be agreed before execution.','inputs':manifest})
    print('Prepared 24 message inputs; no model calls')

if __name__=='__main__': main()
