"""Draw all twelve paired reference repairs from the saved plotting data."""
import argparse, csv, hashlib, json, math, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from paper_style_otf import configure
configure()
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
FIG, DATA = ROOT / "generated", ROOT / "data"
SHORT, LONG, CHARGE, INK, GREY = "#2B5776", "#C66631", "#537B62", "#333A40", "#ADB3B8"
plt.rcParams.update({
    "font.family": "Latin Modern Roman", "font.size": 11,
    "axes.titlesize": 12, "axes.labelsize": 11,
    "xtick.labelsize": 11, "ytick.labelsize": 11,
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK, "ytick.color": INK,
})

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))




def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    # Fixed canvas keeps the reduction to the 408-pt text width explicit.
    for ext in ("pdf", "svg", "png"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=300, facecolor="white")
    plt.close(fig)


def pairs(rows):
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 4.95), sharey=True,
                             gridspec_kw={"width_ratios": [1, 1.12, 1.35]})
    y = [i + (0.6 if i >= 6 else 0) for i in range(12)]
    for ax, key, title, maxi in zip(axes[:2], ("reroutes", "charge_blocks"),
            ("(a) Rerouted missions\nvs. incumbent", "(b) Total charging\nblocks"), (2, 7)):
        for yi, row in zip(y, rows):
            lo, hi = row["short_" + key], row["long_" + key]
            ax.plot([lo, hi], [yi, yi], color=GREY, lw=1.9, zorder=2)
            ax.scatter(lo, yi, facecolor="white", edgecolor=SHORT, s=40, lw=1.5, zorder=3)
            ax.scatter(hi, yi, color=LONG, marker="|", s=105, lw=2, zorder=4)
        ax.set_xlim(-0.25, maxi + 0.45)
        ax.set_xticks(range(maxi + 1) if maxi == 2 else [0, 2, 4, 6])
        ax.set_title(title, loc="left", pad=11)
    axes[0].set_yticks(y, [r["label"] for r in rows])
    axes[0].invert_yaxis()
    axes[0].tick_params(axis="y", pad=7)
    energy = [r["energy_long_minus_short_Wh"] for r in rows]
    axes[2].barh(y, energy, height=0.42, color=LONG)
    axes[2].set_xlim(0, 41)
    axes[2].set_xticks([0, 10, 20, 30, 40])
    axes[2].set_title("(c) Flight energy\nlong − short (Wh)", loc="left", pad=11)
    for yi, value in zip(y, energy):
        axes[2].text(value + 0.8, yi, f"{value:.1f}", va="center", fontsize=11)
    for ax in axes:
        ax.grid(axis="x", color="#E4E7E9", lw=0.6)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_color(GREY)
        ax.tick_params(axis="y", length=0)
        ax.axhline(5.8, color=GREY, lw=0.6)
    handles = [
        Line2D([], [], marker="o", ls="none", markeredgecolor=SHORT, markerfacecolor="white", markersize=6, label="10-min closure"),
        Line2D([], [], marker="|", ls="none", color=LONG, markeredgewidth=2, markersize=10, label="35-min closure"),
    ]
    fig.suptitle("Paired reference repairs", y=0.98, fontsize=12.5)
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.55, 0.005), ncol=2, frameon=False)
    fig.subplots_adjust(left=0.18, right=0.98, wspace=0.34, bottom=0.115, top=0.815)
    save(fig, "new_paired_structure")

if __name__=='__main__':
 pairs(read(DATA/'mechanism_paired_references.json')['rows'])
