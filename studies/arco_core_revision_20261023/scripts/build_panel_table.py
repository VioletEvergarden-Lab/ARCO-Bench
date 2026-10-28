"""Build compact manuscript tables directly from the final structured panel."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf-8'))
panel=read(ROOT/'analysis/origin_target_panel.json')
joint=read(ROOT/'analysis/origin_target_joint.json')
selection=read(ROOT/'analysis/selection_plan.json')['conditions']
assert len([x for x in panel if x['target_prefix']!=5])==128
lookup={(x['record_id'],x['origin'],x['target_prefix'],x['metric']):x for x in panel}
jlookup={(x['record_id'],x['origin'],x['target_prefix']):x for x in joint}
def interval(x,tex=False):
    lo,hi=x['lower_bound'],x['upper_bound']
    return str(lo) if lo==hi else f'[{lo},{hi}]'
def label(rid):
    if rid.startswith('NET_'):return rid[4:].replace('_','-')
    topology,number,duration=rid[4:].split('_')
    return f'{topology.capitalize()} {number}-{duration}'
lines=[];md=[];shown=[]
for item in selection:
    rid=item['record_id']
    origins=read(ROOT/'runs/origin_target'/rid/'origins.json')['decisions']
    same=origins['G']==origins['Gprime']
    for origin in (['G'] if same else ['G','Gprime']):
        display_origin='G=Gprime' if same else origin
        origin_tex=r'$G=G^{\prime}$' if same else (r'$G^{\prime}$' if origin=='Gprime' else '$G$')
        cells=[];mdcells=[]
        for target in (2,3,4,6):
            m=lookup[rid,origin,target,'missions'];u=lookup[rid,origin,target,'chains']
            if same:
                for metric,x in [('missions',m),('chains',u)]:
                    other=lookup[rid,'Gprime',target,metric]
                    assert (x['lower_bound'],x['upper_bound'])==(other['lower_bound'],other['upper_bound'])
            evidence=jlookup[rid,origin,target];status=evidence['status']
            if status=='proved_tradeoff':
                assert (m['lower_bound'],m['upper_bound'],u['lower_bound'],u['upper_bound'])==(2,2,1,1)
                assert (m['mission_changes'],m['chain_changes'])==(2,2)
                assert (u['mission_changes'],u['chain_changes'])==(3,1)
            else:
                assert evidence['feasible'] is True
            suffix=r'^{\dagger}' if status=='proved_tradeoff' else ''
            cells.append('$'+interval(m)+' / '+interval(u)+suffix+'$')
            mdcells.append(interval(m)+' / '+interval(u)+(' †' if suffix else ''))
        lines.append(' & '.join([label(rid),origin_tex]+cells)+r' \\')
        md.append('| '+' | '.join([label(rid),display_origin]+mdcells)+' |')
        shown.append({'record_id':rid,'origin':display_origin,'cells':mdcells})
tex='\n'.join([
r'\begin{table}[tbp]',r'\centering\small',
r'\caption{Adjustment scope by starting plan and recovery target in eight selected network conditions. Each cell reports the marginal minimum numbers of changed missions / UAV chains.}',
r'\label{tab:origin_target_panel_v16}',r'\setlength{\tabcolsep}{5pt}',r'\renewcommand{\arraystretch}{1.12}',
r'\begin{tabular}{@{}llcccc@{}}',r'\toprule',r'Condition & Starting plan & $\mathcal T_2$ & $\mathcal T_3$ & $\mathcal T_4$ & $\mathcal T_6$ \\',r'\midrule',
*lines,r'\bottomrule',r'\end{tabular}',r'\par\smallskip',r'\begin{minipage}{\linewidth}\footnotesize',
r'The two construction rules produce the same starting plan in six conditions, shown as $G=G^{\prime}$. Brackets report valid lower and upper bounds. The incumbent, feasible domain, target reference and tolerances are fixed within each condition. '
r'$\dagger$~The marginal pair $(2,1)$ is infeasible; the attainable alternatives are $(2,2)$ and $(3,1)$. All exact unmarked pairs have joint witnesses; for interval cells, the reported upper-bound pair has a verified witness.',
r'\end{minipage}',r'\end{table}',''])
(ROOT/'writing/05_origin_target_table.tex').write_text(tex,encoding='utf-8')
markdown='\n'.join(['| Condition | Starting plan | T2 | T3 | T4 | T6 |','|---|---|---|---|---|---|',*md,'',
'每格为任务数 / 链数的边际最小值；区间为有效下、上界。† 表示边际对(2,1)不可同时达到，联合选择为(2,2)或(3,1)。六个条件的两种构造产生同一方案，合并展示。区间行的上界预算对有联合见证。',''])
(ROOT/'analysis/origin_target_table.md').write_text(markdown,encoding='utf-8')
report=ROOT/'CORE_REVISION_RESEARCH_REPORT.md'
if report.exists():
    content=report.read_text(encoding='utf-8')
    start='<!-- PANEL_TABLE -->';end='<!-- END_PANEL_TABLE -->'
    assert start in content
    before,tail=content.split(start,1)
    after=tail.split(end,1)[1] if end in tail else tail
    content=before+start+'\n\n'+'\n'.join(markdown.splitlines()[:-2])+'\n\n'+end+after
    report.write_text(content,encoding='utf-8')
(ROOT/'analysis/panel_table_data.json').write_text(json.dumps({'rows':shown,'source_sha256':hashlib.sha256((ROOT/'analysis/origin_target_panel.json').read_bytes()).hexdigest(),'display_rows':len(shown),'conditions':8,'main_scalar_positions':128},indent=2),encoding='utf-8')
print(json.dumps({'display_rows':len(shown),'conditions':8,'scalar_positions':128}))
