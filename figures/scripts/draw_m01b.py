"""Draw the M01-B repair scope and charger schedules from saved event data."""
from pathlib import Path
import argparse,csv,json,sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from paper_style import configure
BASE=Path(__file__).resolve().parents[1]
ORDER=('R4','deepseek','luna')
LABELS={'G':'G','R4':r'Single-pass $R_4$','deepseek':'DeepSeek','luna':'Luna'}
BLUE='#0072B2';ORANGE='#D55E00';INK='#202124';GRAY='#777777'
COLORS={'U01':BLUE,'U02':ORANGE}




def draw(data):
 configure()
 plt.rcParams.update({'font.size':9,'axes.labelsize':9,'xtick.labelsize':8.5,'ytick.labelsize':9,
  'svg.fonttype':'none','pdf.fonttype':42,'text.color':INK,'axes.edgecolor':'#555555',
  'axes.linewidth':.6,'hatch.linewidth':.35,'savefig.facecolor':'white'})
 # TeX text width is 408 TeX pt; the image's physical width matches it.
 width=408/72.27
 fig=plt.figure(figsize=(width,4.95),facecolor='white')
 fig.text(.025,.968,'(a) Changes relative to G',ha='left',va='top',fontsize=10)
 ax=fig.add_axes([.22,.65,.585,.235]);ax.set_xlim(-.55,8.55);ax.set_ylim(-.6,2.8);ax.axis('off')
 missions=data['matrix_missions']
 for j,mid in enumerate(missions):
  ax.text(j,2.38,mid,ha='center',va='center',fontsize=8.5)
  for i,source in enumerate(ORDER):
   y=1.72-i*.85;uid='U01' if j<5 else 'U02';changed=mid in data['plans'][source]['changed_missions']
   ax.add_patch(Rectangle((j-.36,y-.23),.72,.46,facecolor=COLORS[uid] if changed else 'white',
    edgecolor=COLORS[uid] if changed else '#A9A9A9',linewidth=.75))
 for xs,xe,uid in [(-.42,4.42,'U01'),(4.58,8.42,'U02')]:
  ax.plot([xs,xe],[2.70,2.70],color=COLORS[uid],lw=1.1)
  ax.text((xs+xe)/2,2.76,uid,ha='center',va='bottom',fontsize=9,color=COLORS[uid])
 for i,source in enumerate(ORDER):
  y=1.72-i*.85
  ax.text(-.95,y,LABELS[source],ha='right',va='center',fontsize=9,clip_on=False)
  ax.text(9.15,y,f"{data['plans'][source]['mission_changes']} / {data['plans'][source]['chain_changes']}",
   ha='center',va='center',fontsize=9,clip_on=False)
 ax.text(9.15,2.52,'Missions /\nUAVs',ha='center',va='center',fontsize=8.5,clip_on=False)
 # Matrix meaning, common service denominator, and the matched quality candidate.
 fig.text(.22,.626,'Filled: changed    Open: unchanged',fontsize=8.5,ha='left')
 fig.text(.22,.588,'All three plans serve 20/20 missions; DeepSeek attains reference quality.',fontsize=8.5,ha='left')
 fig.text(.025,.533,'(b) V11 charging schedules',ha='left',va='top',fontsize=10)
 ax=fig.add_axes([.185,.15,.725,.305]);ax.set_xlim(41,63.5);ax.set_ylim(-.6,2.65)
 ax.set_yticks([2,1,0]);ax.set_yticklabels([LABELS[s] for s in ORDER]);ax.tick_params(axis='y',length=0,pad=9)
 ax.set_xticks([42,46,50,54,58,62]);ax.set_xlabel('Time (min)',labelpad=5)
 ax.tick_params(axis='x',length=3,width=.6)
 for sp in ('left','right','top'):ax.spines[sp].set_visible(False)
 for tick in [42,46,50,54,58,62]:ax.axvline(tick,color='#E4E4E4',lw=.55,zorder=0)
 for i,source in enumerate(ORDER):
  y=2-i;plan=data['plans'][source]
  for event in plan['V11_events']:
   color=COLORS[event['uav_id']];left=event['booking_union_start'];right=event['booking_union_end']
   # Each minute window remains an editable rectangle, with light hatch.
   for bucket in event['booking_buckets']:
    ax.add_patch(Rectangle((bucket,y-.20),1,.40,facecolor=color+'13',edgecolor=color+'70',
     hatch='///' if event['uav_id']=='U01' else '\\\\\\',linewidth=.35,zorder=1))
   start,end=event['start_min_raw'],event['end_min_raw']
   ax.add_patch(Rectangle((start,y-.095),end-start,.19,facecolor=color,edgecolor=color,lw=.5,zorder=3))
   # Endpoint pairs are placed on opposite sides, never moved in time.
   offset=.31 if event['mission_id']=='M004' else -.31
   textcolor=BLUE if event['uav_id']=='U01' else '#A34500'
   ax.text((start+end)/2,y+offset,f"{event['mission_id']}  {event['interval_display']}",
    ha='center',va='center',color=textcolor,fontsize=8.1,zorder=4)
  ax.text(64.0,y,f"{plan['objective']['weighted_tardiness_min']:.0f}",ha='center',va='center',fontsize=9,clip_on=False)
 ax.text(65.0,2.52,'$L_4$ (weighted min)',ha='right',va='center',fontsize=8.3,clip_on=False)
 # Concise legend with shape as well as color; no conflict marker for Luna.
 solid=Rectangle((0,0),1,1,facecolor='#555555',edgecolor='#555555')
 hatch=Rectangle((0,0),1,1,facecolor='#F4F4F4',edgecolor='#888888',hatch='///',lw=.5)
 fig.legend([solid,hatch],['Continuous charging','Union of 1-min reservations'],loc='lower center',
  bbox_to_anchor=(.545,.006),ncol=2,frameon=False,fontsize=8.5,handlelength=1.7,columnspacing=1.5)
 fig.text(.19,.486,'M004 / U01',color=BLUE,fontsize=8.5)
 fig.text(.44,.486,'M008 / U02',color='#A34500',fontsize=8.5)
 fig.text(.94,.486,'Capacity 1',fontsize=8.5,ha='right')
 # Normal text remains editable in SVG; PDF embeds the supplied Roman fonts.
 folder=BASE/'generated';folder.mkdir(exist_ok=True)
 fig.savefig(folder/'m01b_coordination.pdf',metadata={'Title':'M01-B repair scope and V11 charging schedules'})
 fig.savefig(folder/'m01b_coordination.svg')
 fig.savefig(BASE/'generated/m01b_coordination.png',dpi=220)
 plt.close(fig)

if __name__=='__main__':
 draw(json.loads((BASE/'data/m01b_evidence.json').read_text(encoding='utf8')))
