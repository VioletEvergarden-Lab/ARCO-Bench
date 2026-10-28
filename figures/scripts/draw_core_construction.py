"""Draw a reconstruction of the Core construction summary; the supplied publication artwork is retained separately."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np

BLUE='#377BA8'; RED='#B85959'; GOLD='#DCAC4D'; GRAY='#8996A7'; DARK='#253B50'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,
 'axes.labelsize':9,'xtick.labelsize':8.5,'ytick.labelsize':9,'svg.fonttype':'none',
 'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})

def save(fig,folder,name):
    for ext in ('pdf','svg','png'):
        fig.savefig(folder/f'{name}.{ext}',dpi=450 if ext=='png' else 150,
                    facecolor='white',metadata={'Creator':'ARCO-Bench manuscript build'} if ext=='pdf' else None)
    plt.close(fig)


def figure2(folder):
    """Faithful vector reconstruction of the supplied construction figure."""
    # Existing published construction counts, not newly estimated frequencies.
    counts={'local_route_counts':[1,2,3,4],'missions':[271,132,24,4],
      'total_missions':431,'target_flight_slots':14,'competitor_wait_slots':12,
      'competitor_flight_slots':2,'slot_min':5,'charge_delta_min':-5,
      'L5_delta_min':55,'source':'Supplied main.tex.pdf, construction figure on page 11; unchanged construction summary.'}
    (folder/'Figure2_construction_data.json').write_text(json.dumps(counts,indent=2)+'\n')
    fig=plt.figure(figsize=(7.4,5.45))
    flow=fig.add_axes([.025,.58,.95,.37]);flow.set_axis_off()
    titles=['Feasible\nparent','Controlled\nintervention','Target and\ncompetitor','Certification\nchecks','Admission\nand curation','Core-72']
    texts=['Fixed mission\nchains','Capacities, SOC,\nwindows, routes;\naction\nrestrictions',
      'Optimal target\n'+r'$z^*$'+'\nFeasible\ncompetitor '+r"$z'$",
      'Resource\ncounterfactuals;\nmechanism\nnecessity;\nindependent\nreplay',
      'Reject failed\ntasks; structural\nquotas','72 curated\ntasks']
    colors=['#E5EDF7','#FFF2D3','#FBE3E3','#E5F1DB','#DDF0EF','#E5EDF7']
    w=.149
    for i,(title,text,col) in enumerate(zip(titles,texts,colors)):
        x=i*.17
        flow.add_patch(FancyBboxPatch((x,.10),w,.76,boxstyle='round,pad=0.005',facecolor=col,edgecolor='#9cacba',lw=.6))
        flow.text(x+w/2,.735,title,ha='center',va='center',fontweight='bold',fontsize=8.7,color=DARK)
        flow.text(x+w/2,.355,text,ha='center',va='center',fontsize=8.2,linespacing=1.25)
        if i<5:flow.annotate('',xy=(x+.169,.48),xytext=(x+w+.003,.48),arrowprops=dict(arrowstyle='->',lw=1,color=DARK))
    flow.set_xlim(-.006,1.012);flow.set_ylim(0,1)
    fig.text(.025,.97,'(a) Certificate-first task construction',fontweight='bold',fontsize=10.5,color=DARK)
    hist=fig.add_axes([.09,.23,.30,.27]);hist.bar(counts['local_route_counts'],counts['missions'],color='#79A5C4',width=.6)
    hist.set_xticks([1,2,3,4]);hist.set_ylim(0,315);hist.set_ylabel('Missions');hist.set_xlabel('Locally available routes')
    for x,n in zip(counts['local_route_counts'],counts['missions']):hist.text(x,n+8,str(n),ha='center',fontsize=9)
    hist.grid(axis='y',alpha=.15);hist.set_axisbelow(True)
    fig.text(.025,.53,'(b) Local route availability',fontweight='bold',fontsize=10,color=DARK)
    fig.text(.025,.055,'431 missions; before fleet-wide\nSOC and capacity checks.',fontsize=8.5)
    ax=fig.add_axes([.48,.25,.48,.235]);ax.set_xlim(-.3,14.5);ax.set_ylim(-.35,1.55)
    ax.add_patch(Rectangle((0,.73),14,.35,facecolor='#DCEACD',edgecolor='#567936'))
    ax.add_patch(Rectangle((0,.0),12,.35,facecolor='#F1F1F1',edgecolor=GRAY,ls='--'))
    ax.add_patch(Rectangle((12,.0),2,.35,facecolor='#DCE6F7',edgecolor=BLUE))
    ax.text(7,.91,'Flight: 14 slots',ha='center',va='center',fontsize=9)
    ax.text(6,.17,'Wait: 12 slots',ha='center',va='center',fontsize=9)
    ax.text(13,.17,'2',ha='center',va='center',fontsize=9)
    ax.text(0,1.22,'Target route',fontsize=9,color='#567936');ax.text(0,.45,'Competing route',fontsize=9,color=BLUE)
    ax.set_xticks([0,12,14]);ax.set_xlabel('Slots relative to target departure');ax.set_yticks([])
    ax.spines['left'].set_visible(False)
    fig.text(.455,.53,'(c) Repeated L5 construction pattern',fontweight='bold',fontsize=10,color=DARK)
    fig.text(.48,.10,'At equal L1–L4, competitor minus target:',fontsize=8.5)
    fig.text(.48,.045,'+60 min release-to-departure time\n−5 min charging = +55 min L5',fontsize=9,color='#355824')
    save(fig,folder,'Figure2_construction')

if __name__=='__main__':
 folder=Path(__file__).resolve().parents[1]/'generated'
 folder.mkdir(parents=True,exist_ok=True)
 figure2(folder)
