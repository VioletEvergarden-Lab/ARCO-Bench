"""Editable vector Figure 3 with G/R3 and separate public/offline information flows."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

HERE=Path(__file__).resolve().parent

def main():
    plt.rcParams.update({'font.family':'serif','font.serif':['Times New Roman'],'pdf.fonttype':42,'svg.fonttype':'none'})
    fig,ax=plt.subplots(figsize=(12.0,6.45)); fig.subplots_adjust(0,0,1,1); ax.set_xlim(0,12); ax.set_ylim(0,6.45); ax.axis('off')
    blue='#213e77'; pale='#f2f5fb'; line='#325995'; grey='#3f3f3f'
    def box(x,y,w,h,label,fill='white',edge=None,color=blue,size=15,weight='normal'):
        ax.add_patch(Rectangle((x,y),w,h,facecolor=fill,edgecolor=edge or 'none',linewidth=.8))
        ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=size,color=color,fontweight=weight,linespacing=1.25)
    def arrow(a,b,dashed=False,color='black'):
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=14,linewidth=1.1,color=color,linestyle='--' if dashed else '-'))
    box(.12,3.05,11.76,3.20,'',pale,line); ax.text(.27,6.00,'Public execution: candidate selection',fontsize=19,fontweight='bold',color=blue)
    ax.text(11.7,6.03,'Public task and submitted candidates',ha='right',fontsize=12,color='#777777')
    box(.28,3.35,2.48,2.15,'Public operating state\n\nDisrupted plan\nFixed commitments\nResource calendars\nObjective priorities',size=14)
    box(3.14,4.63,2.72,.86,'Greedy G / local repair R3\nLocal candidate',fill='#fff2c6',size=14)
    box(3.14,3.36,2.72,.86,'Generative model\nModel candidate',fill='#f9dce0',size=15)
    box(6.3,3.35,2.67,2.15,'',fill='#dae3f4'); ax.text(7.635,5.66,'Public evaluation',fontsize=16,ha='center',fontweight='bold',color=blue)
    for y,label in [(4.70,'Parser'),(4.15,'Formal verifier'),(3.60,'Objective and event\nreconstruction')]: box(6.53,y,2.21,.44,label,fill='white',edge=line,size=13)
    arrow((7.63,4.70),(7.63,4.59),color=line); arrow((7.63,4.15),(7.63,4.04),color=line)
    box(9.47,4.59,2.08,.9,'Comparator\nSelected candidate',fill='#e3f1d7',size=15)
    box(9.47,3.35,2.08,.82,'Output\nObjective vector + events',edge=line,size=13)
    arrow((2.76,5.05),(3.14,5.05)); arrow((2.76,3.79),(3.14,3.79)); arrow((5.86,5.05),(6.30,5.05)); arrow((5.86,3.79),(6.30,3.79)); arrow((8.97,5.03),(9.47,5.03)); arrow((8.74,3.81),(9.47,3.81),color=line)
    box(.12,.15,11.76,2.61,'','#f7f7f7','#333333'); ax.text(.27,2.48,'Offline reference evaluation',fontsize=19,fontweight='bold',color='#111111')
    ax.text(11.7,2.50,'Additional research information',ha='right',fontsize=12,color='#777777')
    box(.58,.53,2.43,1.50,'Public reconstruction\n\nObjective vector\nMission and resource events',fill='#dae3f4',size=14)
    for y,title,note,right in [(1.75,'Reference quality','Against optimized objective','MILP reference'),(1.11,'Construct fidelity','Action-pattern diagnostic','Construction annotations'),(.47,'Operating consequences','Service, timing, charging, energy','Reference event trace')]:
        box(3.65,y,4.07,.42,title,fill=grey,color='white',size=15,weight='bold'); box(3.65,y-.22,4.07,.22,note,color=grey,size=11)
        box(8.55,y-.15,2.80,.65,right,fill='#d3d3d3',color='black',size=14,weight='bold')
        arrow((3.01,y+.1),(3.65,y+.1)); arrow((8.55,y+.1),(7.72,y+.1),dashed=True)
    out=HERE/'figures'; out.mkdir(exist_ok=True)
    for suffix in ('pdf','svg','png'): fig.savefig(out/f'figure3.{suffix}',dpi=200,facecolor='white',bbox_inches='tight',pad_inches=.04)
    plt.close(fig)

if __name__=='__main__': main()
