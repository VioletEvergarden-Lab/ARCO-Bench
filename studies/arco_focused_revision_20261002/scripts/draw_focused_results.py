"""Rebuild static manuscript figures from saved result tables; no new solves."""
from pathlib import Path
import argparse, csv, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter, MaxNLocator

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'figures'
DATA=ROOT/'results/figure_data'
BLUE='#355f88'; GOLD='#b98231'; GREY='#777777'; PURPLE='#8b6283'; INK='#272c31'

def setup():
    OUT.mkdir(parents=True,exist_ok=True); DATA.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'Times New Roman','font.size':9,'mathtext.fontset':'stix',
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'axes.labelcolor':INK,'text.color':INK,
        'xtick.color':INK,'ytick.color':INK,'xtick.major.width':.6,'ytick.major.width':.6,
        'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','savefig.facecolor':'white'})

def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write_rows(name, records):
    keys=list(dict.fromkeys(k for r in records for k in r))
    with (DATA/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(records)

def save(fig,name):
    for ext in ('pdf','svg','png'): fig.savefig(OUT/f'{name}.{ext}',dpi=300,bbox_inches='tight',pad_inches=.035)
    plt.close(fig); print(OUT/f'{name}.pdf')

def preference():
    source=ROOT/'results/preference/comparison.json'
    records=json.loads(source.read_text(encoding='utf-8'))
    assert len(records)==36 and all(r['optimal'] for r in records)
    fig,axes=plt.subplots(1,3,figsize=(7.25,4.8),sharex=True)
    fig.subplots_adjust(left=.075,right=.985,bottom=.18,top=.855,wspace=.48)
    export=[]
    for ax,scale,label in zip(axes,'SML',['(a) Small','(b) Medium','(c) Large']):
        subset=sorted([r for r in records if r['scale']==scale],key=lambda r:r['record_id'])
        for y,r in enumerate(subset):
            before=r['original_objective']['weighted_tardiness_min'];after=r['preference_objective']['weighted_tardiness_min']
            ax.plot([before,after],[y,y],color='#b5bac0',lw=1.4,zorder=1)
            ax.scatter(before,y,s=25,facecolors='white',edgecolors=GREY,linewidths=.9,zorder=2)
            ax.scatter(after,y,s=22,color=BLUE,marker='D',linewidths=.4,zorder=3)
            export.append({'record_id':r['record_id'],'scale':scale,'original_weighted_tardiness_min':before,'preference_weighted_tardiness_min':after,
                'waiting_to_rerouting':bool(r['waiting_to_detour_missions']),'original_urgent_on_time':r['original_urgent_on_time'],
                'preference_urgent_on_time':r['preference_urgent_on_time'],'urgent_demand':r['original_urgent_demand']})
        names=[r['record_id'][4:].replace('_','-')+(' *' if r['waiting_to_detour_missions'] else '') for r in subset]
        ax.set_yticks(range(12),names);ax.invert_yaxis();ax.set_ylim(11.65,-.6);ax.set_xlim(-10,550)
        ax.set_xticks([0,250,500]);ax.grid(axis='x',color='#e5e6e7',linewidth=.5);ax.set_axisbelow(True)
        for split in [2.5,5.5,8.5]:ax.axhline(split,color='#ededed',lw=.6,zorder=0)
        ax.set_title(label,loc='left',fontweight='bold',fontsize=10,pad=12)
        old=sum(r['original_urgent_on_time'] for r in subset);new=sum(r['preference_urgent_on_time'] for r in subset);n=sum(r['original_urgent_demand'] for r in subset)
        ax.text(.5,-.17,f'Urgent on time: {old} → {new} (n={n})',ha='center',transform=ax.transAxes,fontsize=8.1)
    handles=[Line2D([0],[0],marker='o',markerfacecolor='white',markeredgecolor=GREY,color='none',markersize=5,label=r'Original: $L_3$ before $L_4$'),
             Line2D([0],[0],marker='D',color=BLUE,linestyle='none',markersize=4.5,label=r'Tardiness first: $L_4$ before $L_3$')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.52,.98),ncol=2,frameon=False,handletextpad=.6,columnspacing=2.)
    fig.text(.53,.11,'Weighted tardiness (weighted min)',ha='center',fontsize=9.5)
    fig.text(.075,.02,'* Waiting-to-rerouting change. Both settings retain the two service objectives first.',fontsize=8.3)
    write_rows('preference_pairs.csv',export);save(fig,'preference_pairs')

def physics():
    raw=rows(ROOT/'results/physics/stress_summary.csv')
    by={}
    for r in raw:
        item={**r,'power_increase':float(r['power_increase']),'available_plans':int(r['available_plans']),
              'admissible':int(r['admissible']),'minimum_reserve_margin_wh':float(r['minimum_reserve_margin_wh'])}
        item['feasible_fraction']=item['admissible']/item['available_plans'];by.setdefault(r['source'],[]).append(item)
    for k in by:by[k].sort(key=lambda r:r['power_increase'])
    assert len(by)==5 and all(len(v)==4 for v in by.values())
    # These independently evaluated methods have identical displayed points.
    assert all(a['admissible']==b['admissible'] and abs(a['minimum_reserve_margin_wh']-b['minimum_reserve_margin_wh'])<1e-9 for a,b in zip(by['R4'],by['luna']))
    specifications=[('Reference','Reference (n=36)',BLUE,'o','-'),('G','G (n=36)',GREY,'s','--'),
        ('R4',r'$R_4$ / Luna (n=36 each)',GOLD,'^','-.'),('deepseek','DeepSeek (n=28)',PURPLE,'D',':')]
    fig,axes=plt.subplots(1,2,figsize=(7.25,3.05));fig.subplots_adjust(left=.09,right=.975,bottom=.19,top=.76,wspace=.38)
    for key,name,color,mark,line in specifications:
        points=by[key];xx=[100*r['power_increase'] for r in points]
        for ax,field in zip(axes,['feasible_fraction','minimum_reserve_margin_wh']):
            ax.plot(xx,[r[field] for r in points],color=color,marker=mark,linestyle=line,lw=1.25,ms=4.8,
                markerfacecolor='white' if key in ('G','Reference') else color,markeredgewidth=.8,label=name)
    for ax in axes:
        ax.set_xlim(-.2,10.25);ax.set_xticks([0,2,5,10]);ax.set_xlabel('Flight-stage power increase (%)');ax.grid(axis='y',lw=.5,color='#e7e7e7');ax.set_axisbelow(True)
    axes[0].set_ylim(0,1.05);axes[0].yaxis.set_major_formatter(PercentFormatter(1));axes[0].set_ylabel('Plans retaining feasibility')
    axes[0].set_title('(a) Fixed-plan feasibility',loc='left',fontweight='bold',fontsize=10,pad=9)
    axes[1].axhline(0,lw=.65,color=INK);axes[1].set_ylim(-6.5,.5);axes[1].set_ylabel('Minimum reserve margin (Wh)')
    axes[1].set_title('(b) Minimum postflight margin',loc='left',fontweight='bold',fontsize=10,pad=9)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,ncol=2,frameon=False,loc='upper center',bbox_to_anchor=(.52,1.),fontsize=8.6,columnspacing=2.1)
    write_rows('power_stress.csv',[r for v in by.values() for r in v]);save(fig,'power_stress')

def comparison(new=False):
    folder='new_comparison' if new else 'comparison'
    expected=24 if new else 36
    path=ROOT/f'results/{folder}/budget_slices.csv'
    if not path.exists():
        print(f'Timing figure awaits results/{folder}/budget_slices.csv.');return False
    raw=rows(path);methods=['G','R4','Full-MILP','Iter-R4','R_frac'];cuts=[30,60,180,300,600]
    def truth(x):return str(x).lower()=='true'
    by={}
    for r in raw:
        key=(r['record_id'],r['method'],float(r['seconds']))
        if key in by:raise ValueError(('duplicate budget slice',key))
        by[key]=r
    ids=sorted({r['record_id'] for r in raw})
    if len(ids)!=expected or any((rid,m,float(t)) not in by for rid in ids for m in methods for t in cuts):
        print(f'Timing figure awaits complete {expected}-task, five-method matrix in {folder}.');return False
    summary=[]
    for method in methods:
        for t in cuts:
            subset=[by[rid,method,float(t)] for rid in ids]
            summary.append({'method':method,'seconds':t,'tasks':len(ids),
                'admissible':sum(truth(r['admissible']) for r in subset),
                'service_target':sum(truth(r['service_target']) for r in subset),
                'reference_certified':sum(truth(r['reference_certified']) for r in subset),
                'reference_quality':sum(truth(r['reference_quality']) and truth(r['reference_certified']) for r in subset)})
    denominators={r['reference_certified'] for r in summary}
    if len(denominators)!=1:raise ValueError('Certified-reference denominator changes across methods or budgets.')
    qden=next(iter(denominators))
    fig,axes=plt.subplots(1,3,figsize=(7.25,3.0),sharey=True)
    fig.subplots_adjust(left=.075,right=.985,bottom=.24,top=.75,wspace=.19)
    styles={'G':(GREY,'s','--'),'R4':(GOLD,'^','-.'),'Full-MILP':(BLUE,'o','-'),
        'Iter-R4':(PURPLE,'D',':'),'R_frac':('#6f7d47','v',(0,(4,1,1,1)))}
    labels={'G':'G','R4':r'$R_4$','Full-MILP':'Full-MILP','Iter-R4':r'Iter-$R_4$','R_frac':r'$R_{\mathrm{frac}}$'}
    for method in methods:
        points=[r for r in summary if r['method']==method];color,mark,line=styles[method]
        for ax,field in zip(axes,['admissible','service_target','reference_quality']):
            ax.plot(cuts,[r[field] for r in points],color=color,marker=mark,linestyle=line,lw=1.15,ms=4.3,
                markerfacecolor='white' if method in ('G','Full-MILP') else color,markeredgewidth=.8,label=labels[method])
    for ax,title in zip(axes,['(a) Feasible plan','(b) Service target','(c) Reference quality']):
        ax.set_xlim(20,620);ax.set_xticks([30,180,300,600]);ax.set_ylim(-.6,expected+1.2)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True,nbins=5));ax.set_xlabel('Response budget (s)')
        ax.grid(axis='y',color='#e7e7e7',lw=.5);ax.set_axisbelow(True);ax.set_title(title,loc='left',fontweight='bold',fontsize=9.5,pad=10)
    axes[0].set_ylabel('Tasks with an available plan')
    handles,names=axes[0].get_legend_handles_labels();fig.legend(handles,names,ncol=5,frameon=False,loc='upper center',bbox_to_anchor=(.52,.98),fontsize=8.8,columnspacing=1.6)
    fig.text(.075,.075,f'All tasks: n={expected}; certified reference-quality targets: n={qden}.',fontsize=8.2)
    fig.text(.075,.025,'Historical model responses are not part of this common online timing experiment.',fontsize=8.2)
    name='new_time_service_quality' if new else 'time_service_quality'
    write_rows(name+'.csv',summary);save(fig,name);return True

def main():
    p=argparse.ArgumentParser();p.add_argument('--only',choices=['all','preference','physics','comparison'],default='all');a=p.parse_args();setup()
    if a.only in ('all','preference'):preference()
    if a.only in ('all','physics'):physics()
    if a.only in ('all','comparison'):
        comparison();comparison(new=True)

if __name__=='__main__':main()
