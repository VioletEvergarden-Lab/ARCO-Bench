"""Draw the Regions S02 routes, delivery events and battery trajectories."""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from paper_style import configure
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
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK, "ytick.color": INK,
})


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    # Fixed canvas keeps the reduction to the 408-pt text width explicit.
    for ext in ("pdf", "svg", "png"):
        out = FIG
        fig.savefig(out / f"{name}.{ext}", dpi=300, facecolor="white")
    plt.close(fig)

def route_segment(ax, xy, color, ls, offset=0.0):
    # Offset only the drawing of the one shared corridor, not the route geometry.
    x0, y0 = xy[0]; x1, y1 = xy[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    dx, dy = -(y1 - y0) * offset / length, (x1 - x0) * offset / length
    ax.plot([p[0] + dx for p in xy], [p[1] + dy for p in xy], color=color, ls=ls, lw=2, zorder=2)
    ax.annotate("", xy=(x0 + .69 * (x1 - x0) + dx, y0 + .69 * (y1 - y0) + dy),
                xytext=(x0 + .46 * (x1 - x0) + dx, y0 + .46 * (y1 - y0) + dy),
                arrowprops={"arrowstyle": "-|>", "color": color, "lw": 1.6, "mutation_scale": 12}, zorder=3)

def case(d):
    fig = plt.figure(figsize=(7.2, 8.3))
    grid = fig.add_gridspec(3, 1, height_ratios=[1.08, .93, 1.05], hspace=.70)
    a, b, c = [fig.add_subplot(grid[i, 0]) for i in range(3)]
    pos = {v["vertiport_id"]: v["xy_km"] for v in d["nodes"]}
    corridors = {r["corridor_id"]: r for r in d["corridors"]}
    seen = set()
    for edge in d["corridors"]:
        key = tuple(sorted((edge["origin"], edge["destination"])))
        if key not in seen:
            a.plot(*zip(*edge["geometry_xy_km"]), color="#D8DCDF", lw=1, zorder=0)
            seen.add(key)
    common = set(d["paths"]["short"]["corridor_ids"]) & set(d["paths"]["long"]["corridor_ids"])
    for cond, color, ls, offset in (("short", SHORT, "--", .010), ("long", LONG, "-", -.010)):
        for cid in d["paths"][cond]["corridor_ids"]:
            route_segment(a, corridors[cid]["geometry_xy_km"], color, ls, offset if cid in common else 0)
    edge = corridors[d["closures"]["long"]["resource"]]
    xy = edge["geometry_xy_km"]
    a.scatter(sum(p[0] for p in xy) / len(xy), sum(p[1] for p in xy) / len(xy), marker="x", color=INK, s=70, lw=1.8, zorder=5)
    for node, point in pos.items():
        a.scatter(*point, marker="s" if d["charger_capacity"][node] > 0 else "o",
                  s=65, facecolor="white", edgecolor=INK, lw=1, zorder=4)
        label = node + (" (origin)" if node == "V02" else " (destination)" if node == "V06" else "")
        offset = {"V01": (5, -15), "V02": (-6, 12), "V03": (-4, 10), "V04": (0, -17),
                  "V05": (0, 11), "V06": (10, 12), "V07": (0, -17)}[node]
        a.annotate(label, point, xytext=offset, textcoords="offset points", ha="center", fontsize=11)
    a.set_xlim(-.80, .80); a.set_ylim(-.43, .43)
    a.set_aspect("equal", adjustable="datalim"); a.axis("off")
    a.set_title("(a) Regions S02: M009 reference routes", loc="left", pad=14)
    route_handles = [
        Line2D([], [], color=SHORT, ls="--", lw=2, label=f"10-min closure: P1 ({1000*d['paths']['short']['energy_kwh']:.3f} Wh)"),
        Line2D([], [], color=LONG, lw=2, label=f"35-min closure: P2 ({1000*d['paths']['long']['energy_kwh']:.3f} Wh)"),
        Line2D([], [], marker="s", ls="none", markerfacecolor="white", color=INK, label="Charging facility"),
        Line2D([], [], marker="x", ls="none", color=INK, label="V02→V01 closed"),
    ]
    a.legend(handles=route_handles, loc="upper center", bbox_to_anchor=(.5, -.03), ncol=2,
             frameon=False, columnspacing=1.8, handlelength=2.4, fontsize=11)

    for yi, cond, color in ((1, "short", SHORT), (0, "long", LONG)):
        for segment in d["timing_segments"][cond]:
            left, right, kind = segment["start_min"], segment["end_min"], segment["kind"]
            if right <= left:
                continue
            fill = {"turnaround": GREY, "charging": CHARGE, "waiting": "white", "M009_flight": color}[kind]
            b.barh(yi, right - left, left=left, height=.27, color=fill,
                   edgecolor=INK if kind == "waiting" else fill, linewidth=.65,
                   hatch="////" if kind == "waiting" else None, zorder=3)
            if kind == "turnaround":
                b.text((left + right) / 2, yi, f"{right-left:g} min", ha="center", va="center", color=INK, fontsize=11)
        final = d["events"][cond]["M009"]
        b.scatter(final["depart_min"], yi, marker="o", s=20, color=color, zorder=4)
        b.scatter(final["arrival_min"], yi, marker="D", s=24, color=color, zorder=4)
        b.annotate(f"Depart {final['depart_min']}", (final["depart_min"], yi), xytext=(-2, 13),
                   textcoords="offset points", ha="right", color=color, fontsize=11)
        b.annotate(f"Arrive {final['arrival_min']:.3f}", (final["arrival_min"], yi), xytext=(2, -18),
                   textcoords="offset points", ha="left", color=color, fontsize=11)
    pre = d["events"]["long"]["M008"]
    b.text((pre["charge_start_min"] + pre["finish_min"]) / 2, 0, f"{pre['charge_blocks']} blocks · {pre['finish_min']-pre['charge_start_min']:g} min",
           color="white", ha="center", va="center", fontsize=11)
    b.annotate(f"M008 arrival {pre['arrival_min']:.3f}", (pre["arrival_min"], 1),
               xytext=(0, 36), textcoords="offset points", ha="left", fontsize=11)
    b.axvline(pre["arrival_min"], ymin=.12, ymax=.8, color=GREY, lw=.7, zorder=0)
    due, horizon = d["mission"]["due_min"], d["horizon_departure_min"]
    b.axvline(due, color="#777E83", ls="-.", lw=.8, zorder=0)
    b.text(due - .3, 1.60, f"Due {due:.3f}", ha="right", va="bottom", fontsize=11)
    b.axvline(horizon, color=INK, ls=":", lw=1.1, zorder=0)
    b.text(horizon + .2, 1.38, f"Departure limit\nH = {horizon:g}", ha="left", va="bottom", fontsize=11)
    b.set_yticks([0, 1], ["35-min", "10-min"])
    b.set_xlim(16, 42.2); b.set_ylim(-.58, 1.88)
    b.set_xticks([20, 25, 30, 35, 40]); b.set_xlabel("Time (min)", labelpad=2)
    b.set_title("(b) U03 from M008 arrival to M009 arrival", loc="left", pad=14)
    b.spines["left"].set_visible(False); b.tick_params(axis="y", length=0)
    b.legend(handles=[Patch(facecolor=GREY, label="Turnaround"), Patch(facecolor=CHARGE, label="Charging"),
                      Patch(facecolor="white", edgecolor=INK, hatch="////", label="Waiting"),
                      Line2D([], [], color=INK, lw=3, label="M009 flight")],
             loc="upper center", bbox_to_anchor=(.5, -.30), ncol=4, frameon=False,
             fontsize=11, handlelength=1.4, columnspacing=1.3)

    # Event stages do not imply counterfactual departure or arrival times.
    x = [0, 1, 2]
    sh = d["events"]["short"]
    short_values = [sh["M008"]["soc_arrival_kwh"] * 1000, sh["M009"]["soc_before_kwh"] * 1000,
                    sh["M009"]["soc_arrival_kwh"] * 1000]
    c.plot(x, short_values, color=SHORT, ls="--", marker="o", ms=4, lw=1.8, label="Short P1 reference")
    for ent, color, ls, marker, label in zip(d["same_P2_detour_charge_comparison"],
            ("#666C72", "#666C72", LONG), ((0, (5, 3)), (0, (1, 2)), "-"), ("x", "+", "s"),
            ("P2, 0 blocks (counterfactual)", "P2, 1 block (counterfactual)", "Long P2 reference, 2 blocks")):
        vals = [ent["M008_arrival_Wh"], ent["M009_departure_Wh"], ent["M009_arrival_Wh"]]
        c.plot(x, vals, color=color, ls=ls, marker=marker, ms=5, lw=1.7, label=label)
    reserve = d["reserve_Wh"]
    c.axhline(reserve, color=INK, ls=":", lw=1)
    c.text(-.02, reserve + 1.5, f"Reserve {reserve:.3f} Wh", fontsize=11)
    c.annotate(f"{short_values[0]:.3f}", (0, short_values[0]), xytext=(6, 9), textcoords="offset points", ha="left", fontsize=11)
    arrivals = [(d["same_P2_detour_charge_comparison"][2]["M009_arrival_Wh"], LONG, 13),
                (short_values[2], SHORT, 0),
                (d["same_P2_detour_charge_comparison"][1]["M009_arrival_Wh"], "#666C72", -10),
                (d["same_P2_detour_charge_comparison"][0]["M009_arrival_Wh"], "#666C72", -14)]
    for value, color, dy in arrivals:
        c.annotate(f"{value:.3f}", (2, value), xytext=(15, dy), textcoords="offset points",
                   color=color, fontsize=11, va="center", arrowprops={"arrowstyle": "-", "color": color, "lw": .7})
    c.set_xlim(-.1, 2.38); c.set_ylim(0, 60)
    c.set_yticks([0, 20, 40, 60]); c.set_ylabel("Battery energy (Wh)")
    c.set_xticks(x, ["M008 arrival", "Before M009", "M009 arrival"])
    c.grid(axis="y", color="#E5E8EA", lw=.6); c.set_axisbelow(True)
    c.set_title("(c) Battery energy: reference and P2 charging alternatives", loc="left", pad=13)
    handles, labels = c.get_legend_handles_labels()
    order = [0, 3, 1, 2]
    c.legend([handles[i] for i in order], [labels[i] for i in order], loc="upper center",
             bbox_to_anchor=(.49, -.20), ncol=2, frameon=False, fontsize=11, columnspacing=1.25, handlelength=2.3)
    fig.subplots_adjust(left=.13, right=.975, top=.95, bottom=.115)
    save(fig, "new_route_energy_case")

if __name__ == "__main__":
    case(read(DATA / "mechanism_regions_S02.json"))
    print("Wrote Regions S02 PDF, SVG and PNG.")
