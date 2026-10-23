"""PP-533 load test renderer: every run in results/ -> figures/ + RESULTS.md.

Runs with no stack (`run.sh render`). Only runs with status ok, the real detector
and full-length timing are charted; everything else is listed in RESULTS.md so
nothing silently disappears. `--include-stub` lets stub/quick runs into the
figures for harness dry-runs only. Hand-written RESULTS.md blocks
(<!-- hand:NAME -->...<!-- /hand:NAME -->) survive every regeneration.

Stdlib + matplotlib only; matplotlib is imported inside the plot code so the
tests (test_render.py) need nothing but the stdlib.
"""
import argparse
import csv
import functools
import gzip
import json
import re
import statistics
import textwrap
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
P95_LIMIT_MS = 10_000
ERR_LIMIT = 0.01

# dataviz reference palette, light mode (categorical slots 1-3 validate all-pairs).
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, CRITICAL = "#e1e0d9", "#c3c2b7", "#d03b3b"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]

MODEL_NAMES = {"desklib": "desklib", "baseline": "baseline (RoBERTa)", "stub": "stub detector"}
RAMP = {"ramp-idle": "idle", "ramp-batch": "under batch"}
HEAD = {"headline-idle": "idle", "headline-loaded": "loaded"}
KEEP = {"check_ok", "check_ok_duration", "http_reqs", "http_req_duration", "dropped_iterations"}
FIGS = {
    1: "Calibration: serial single-check latency (S)",
    2: "Ramp: latency vs. offered rate",
    3: "Ramp: errors, 504s and dropped iterations per step",
    4: "Headline: p50/p95/p99, idle vs. loaded",
    5: "Timeline of a loaded headline run",
    6: "Container CPU and memory during a loaded headline run",
    7: "create_batch freeze, before vs. after fix",
    8: "Model comparison",
}

# ---- pure logic (tested) ----------------------------------------------------------


def pct(values, p):
    """Linear-interpolated percentile (numpy's default); None for no data."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def measured(rows):
    """Rows of the measured `checks` scenario (never warm-up) plus untagged drops."""
    return [r for r in rows if r["scenario"] == "checks"
            or (r["metric"] == "dropped_iterations" and not r["scenario"])]


def check_stats(rows):
    """Latency of successful checks only, so a fast error never looks like good latency."""
    ok_ms = [r["value"] for r in rows if r["metric"] == "check_ok_duration"]
    flags = [r["value"] for r in rows if r["metric"] == "check_ok"]
    reqs = [r for r in rows if r["metric"] == "http_reqs" and r["kind"] == "check"]
    return {
        "n": len(flags),
        "n_ok": len(ok_ms),
        "p50_ms": pct(ok_ms, 50), "p95_ms": pct(ok_ms, 95), "p99_ms": pct(ok_ms, 99),
        "error_rate": (1 - sum(flags) / len(flags)) if flags else None,
        "n504": sum(r["status"] == "504" for r in reqs),
        "dropped": int(sum(r["value"] for r in rows if r["metric"] == "dropped_iterations")),
        "n_req": len(reqs),
    }


def step_stats(rows, steps_per_min=()):
    """Per ramp step stats from the step-tagged `checks` rows.

    dropped_iterations carry no step tag: each goes to the step whose window
    [first, last step-tagged row] starts nearest before it.
    """
    rows = measured(rows)
    groups = {}
    for r in rows:
        if r["step"] is not None:
            groups.setdefault(r["step"], []).append(r)
    if not groups:
        return []
    win = {i: (min(r["ts"] for r in g), max(r["ts"] for r in g)) for i, g in groups.items()}
    first = min(win, key=lambda i: win[i][0])
    for r in rows:
        if r["metric"] == "dropped_iterations" and r["step"] is None:
            before = [i for i in win if win[i][0] <= r["ts"]]
            groups[max(before, key=lambda i: win[i][0]) if before else first].append(r)
    out = []
    for i in sorted(groups):
        st = check_stats(groups[i])
        a, b = win[i]
        out.append({
            "step": i,
            "rate_per_min": steps_per_min[i] if i < len(steps_per_min) else None,
            **st,
            # n completions span n-1 intervals; k6 stamps a request at completion, so this is
            # completion throughput, not arrival rate.
            "achieved_per_min": (st["n_req"] - 1) / ((b - a) / 60000) if st["n_req"] > 1 and b > a else None,
        })
    return out


def find_points(steps):
    """Degradation onset (p95 >= 2x the lowest step's p95) and breaking point
    (p95 > 10 s, errors > 1%, any 504, any dropped iteration), as offered rates.
    Steps are in ramp order; a step with no successful check (p95 None) is broken."""
    if not steps:
        return {"onset": None, "breaking": None}
    base = min(steps, key=lambda s: s["rate_per_min"] or 0)["p95_ms"]  # lowest-rate step
    onset = next((s["rate_per_min"] for s in steps
                  if s["p95_ms"] is None or (base and s["p95_ms"] >= 2 * base)), None)
    breaking = next((s["rate_per_min"] for s in steps
                     if s["p95_ms"] is None or s["p95_ms"] > P95_LIMIT_MS
                     or (s["error_rate"] or 0) > ERR_LIMIT or s["n504"] > 0 or s["dropped"] > 0), None)
    return {"onset": onset, "breaking": breaking}


HAND = re.compile(r"(<!-- hand:([\w-]+) -->)(.*?)(<!-- /hand:\2 -->)", re.S)


def merge_hand_blocks(old, new):
    """Copy hand-written blocks from old into new. A block whose name the new template no
    longer has is appended under "Orphaned hand blocks" (markers kept) instead of lost."""
    kept = {m.group(2): m.group(3) for m in HAND.finditer(old)}
    names = {m.group(2) for m in HAND.finditer(new)}
    out = HAND.sub(lambda m: m.group(1) + kept.get(m.group(2), m.group(3)) + m.group(4), new)
    orphans = [f"<!-- hand:{n} -->{body}<!-- /hand:{n} -->" for n, body in kept.items() if n not in names]
    if orphans:
        out = (out.rstrip("\n") + "\n\n## Orphaned hand blocks\n\n_Hand-written blocks whose section no "
               "longer exists. Move the text where it belongs, then delete the block._\n\n"
               + "\n\n".join(orphans) + "\n")
    return out


# ---- loading ----------------------------------------------------------------------


def to_ms(ts):
    ts = float(ts)
    return ts * 1000 if ts < 1e11 else ts  # older runs wrote unix seconds


def load_requests(path):
    rows = []
    if not path.exists():
        return rows
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            m = r["metric_name"]
            if m not in KEEP:
                continue
            tags = parse_qs(r.get("extra_tags") or "")
            kind = tags.get("kind", [""])[0]
            if m.startswith("http_req") and kind not in ("check", "health"):
                continue
            step = tags.get("step")
            rows.append({"metric": m, "ts": to_ms(r["timestamp"]), "value": float(r["metric_value"]),
                         "scenario": r["scenario"], "status": r["status"], "kind": kind,
                         "step": int(step[0]) if step else None})
    return rows


def mem_gib(s):
    m = re.match(r"([\d.]+)\s*([A-Za-z]*)", s or "")
    if not m:
        return None
    unit = {"b": 1, "kib": 2**10, "mib": 2**20, "gib": 2**30, "kb": 1e3, "mb": 1e6, "gb": 1e9}
    return float(m.group(1)) * unit.get(m.group(2).lower(), 1) / 2**30


def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class Run:
    def __init__(self, d):
        self.id, self.dir = d.name, d
        try:
            self.meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.meta = {"status": "invalid", "status_reason": "meta.json missing or unreadable"}
        m = self.meta
        self.phase = m.get("phase") or (d.name.split("_", 2)[-1] if d.name.count("_") >= 2 else "?")
        self.model = "stub" if m.get("detector") == "stub" else m.get("model", "?")
        self.status = m.get("status", "?")

    @functools.cached_property
    def rows(self):
        return load_requests(self.dir / "requests.csv.gz")

    @functools.cached_property
    def batches(self):
        return read_csv(self.dir / "batches.csv")

    @functools.cached_property
    def stats(self):
        return [{"t": to_ms(r["epoch_s"]), "name": r["name"].replace("prompt-patrol-loadtest-", "").rsplit("-", 1)[0],
                 "cpu": float(r["cpu_pct"] or 0), "mem": mem_gib(r["mem_usage"])}
                for r in read_csv(self.dir / "stats.csv")]

    def t0(self):
        try:
            m = re.search(r"^T0,(\d+)", (self.dir / "k6.log").read_text(errors="replace"), re.M)
            return float(m.group(1)) if m else None
        except OSError:
            return None

    def t_ref(self):
        """Zero of every timeline: the (first) batch submission, else the scenario clock."""
        b = self.batches
        if b and b[0].get("submit_epoch_ms"):
            return float(b[0]["submit_epoch_ms"])
        return self.t0() or min((r["ts"] for r in self.rows), default=0)

    def drain_s(self):
        b = self.batches
        if not b or not b[0].get("drain_end_epoch_ms") or not b[0].get("submit_epoch_ms"):
            return None
        return (float(b[0]["drain_end_epoch_ms"]) - float(b[0]["submit_epoch_ms"])) / 1000

    def submit_ms(self):
        b = self.batches
        return float(b[0]["submit_ms"]) if b and b[0].get("submit_ms") else None

    def peak_detector_gib(self):
        return max((s["mem"] for s in self.stats if s["name"] == "detector" and s["mem"]), default=None)


def name(model):
    return MODEL_NAMES.get(model, model)


def ramp_pick(ramps, model, phase):
    """Newest (run, steps) of one model's ramp phase, or None."""
    hit = [(r, st) for r, st in ramps if r.model == model and r.phase == phase]
    return hit[-1] if hit else None


def newest(runs, **match):
    hits = [r for r in runs if all(getattr(r, k) == v for k, v in match.items())]
    return hits[-1] if hits else None


# ---- plotting -----------------------------------------------------------------------


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 9,
        "text.color": INK, "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.titlecolor": INK, "axes.labelsize": 8.5, "axes.labelcolor": INK2,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.7,
        "axes.axisbelow": True, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE, "xtick.color": AXIS, "ytick.color": AXIS,
        "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "lines.linewidth": 1.6,"lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.fontsize": 8, "svg.fonttype": "none",
    })
    return plt


def _fig(title, nrows=1, ncols=1, w=7.5, h=3.6, **kw):
    plt = _plt()
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), layout="constrained", squeeze=False, **kw)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, fontweight="bold")
    return fig, axes


def _save(fig, out_dir, n, slug, runs, written):
    import matplotlib.pyplot as plt
    models = ", ".join(sorted({name(r.model) for r in runs}))
    cpu = ((runs[0].meta.get("host") or {}) if runs else {}).get("cpu_model") or "unknown host"
    foot = f"{models} · {cpu} · runs: {', '.join(r.id for r in runs)}"
    # Reserve a strip under the layout for the footnote, so it can't collide with the bottom legend.
    w, h = fig.get_size_inches()
    lines = textwrap.wrap(foot, int(w * 18), break_on_hyphens=False)
    strip = (0.1 + 0.11 * len(lines)) / h
    fig.get_layout_engine().set(rect=(0, strip, 1, 1 - strip))
    fig.text(0.012, strip - 0.04 / h, "\n".join(lines), fontsize=6.5, color=MUTED, ha="left", va="top")
    # The layout reserves the outside legend's room inside rect, but anchors the legend to the
    # figure edge: solve once, freeze, then lift the legend above the footnote strip.
    fig.canvas.draw()
    fig.set_layout_engine("none")
    for leg in fig.legends:
        leg.set_bbox_to_anchor((0, strip), transform=fig.transFigure)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(out_dir / "figures" / f"{n}-{slug}.{ext}", dpi=300)
    plt.close(fig)
    written[n] = f"figures/{n}-{slug}.png"


def _ms_axis(ax, log=False):
    from matplotlib.ticker import FuncFormatter
    if log:
        ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
    ax.set_ylabel("Latency (ms)")


def _limit_line(ax, label="10 s limit"):
    ax.axhline(P95_LIMIT_MS, color=CRITICAL, lw=1)
    # Left end: low rates / early times sit far below the limit, so the label stays clear of data.
    ax.annotate(label, (0, P95_LIMIT_MS), xycoords=("axes fraction", "data"), xytext=(3, 3),
                textcoords="offset points", ha="left", va="bottom", fontsize=7.5, color=INK2)


def _legend(ax, **kw):
    """Figure legend below the panels; 'outside' makes constrained layout reserve room for it
    (an axes-owned legend wider than its panel pushes the other columns apart)."""
    kw.setdefault("title_fontsize", 7.5)
    ax.figure.legend(loc="outside lower left", alignment="left", **kw)


def _dots(ax,x, y, color, label=None, marker="o", size=9):
    if len(x):  # an empty series gets no legend entry
        ring = {} if marker == "x" else {"edgecolors": SURFACE, "linewidths": 0.4}
        ax.scatter(x, y, s=size, color=color, marker=marker, label=label, zorder=3, **ring)


def fig_calibration(runs, out_dir, written):
    models = sorted({r.model for r in runs})
    picks = [newest(runs, model=m) for m in models]
    fig, axes = _fig("Phase 1 · Single-check latency when checks run one at a time",
                     len(picks), 1, h=1.0 + 2.0 * len(picks))
    for ax, run in zip(axes[:, 0], picks):
        ok = [r["value"] for r in measured(run.rows) if r["metric"] == "check_ok_duration"]
        med = statistics.median(ok)
        ax.hist(ok, bins=30, color=SERIES[0], edgecolor=SURFACE, linewidth=0.6)
        ax.axvline(med, color=INK, lw=1)
        ax.annotate(f"median S = {med:,.0f} ms\n→ capacity ≈ {60000 / med:,.0f} req/min", (med, 1),
                    xycoords=("data", "axes fraction"), xytext=(5, -2), textcoords="offset points",
                    va="top", fontsize=8, color=INK,
                    bbox={"boxstyle": "square,pad=0.2", "fc": SURFACE, "ec": "none"})
        ax.set_title(f"{name(run.model)} · {len(ok)} serial checks")
        ax.set_xlabel("Latency of a successful check (ms)")
        ax.set_ylabel("Checks")
    _save(fig, out_dir, 1, "calibration", picks, written)


def fig_ramp(ramps, out_dir, written):
    from matplotlib.lines import Line2D
    models = sorted({r.model for r, _ in ramps})
    fig, axes = _fig("Phase 3 · Where single checks start to break as the offered rate climbs",
                     1, len(models), h=4.2, sharey=True)
    used = []
    ymin, ymax = float("inf"), P95_LIMIT_MS  # y is shared, so one range across all panels
    for ax, model in zip(axes[0], models):
        for slot, phase in enumerate(RAMP):
            hit = ramp_pick(ramps, model, phase)
            if not hit:
                continue
            run, steps = hit
            used.append(run)
            c = SERIES[slot]
            xs = [s["rate_per_min"] for s in steps]
            nan = float("nan")
            p50, p95, p99 = ([s[k] if s[k] is not None else nan for s in steps] for k in ("p50_ms", "p95_ms", "p99_ms"))
            ax.fill_between(xs, p50, p99, color=c, alpha=0.12, lw=0)
            ax.plot(xs, p95, color=c, marker="o", ms=5, mec=SURFACE, mew=1.2, zorder=3)
            ymin = min([ymin] + [v for v in p50 if v == v])
            ymax = max([ymax] + [v for v in p99 if v == v])
            pts = find_points(steps)
            y_at = {s["rate_per_min"]: s["p95_ms"] or P95_LIMIT_MS for s in steps}
            if pts["onset"] is not None:
                ax.plot(pts["onset"], y_at[pts["onset"]], marker="D", ms=9, mfc=SURFACE, mec=c, mew=1.8, zorder=4)
            if pts["breaking"] is not None:
                ax.plot(pts["breaking"], y_at[pts["breaking"]], marker="X", ms=11, color=c, mec=SURFACE, mew=1, zorder=5)
            pred = run.meta.get("predicted_breaking_per_min")
            if pred:
                ax.axvline(pred, color=c, lw=1, ls=(0, (2, 2)))
        _ms_axis(ax, log=True)
        _limit_line(ax)
        ax.set_title(name(model))
        ax.set_xlabel("Offered rate (req/min)")
    if ymin < float("inf"):
        axes[0][0].set_ylim(ymin * 0.7, ymax * 1.6)
    for ax in axes[0][1:]:
        ax.set_ylabel("")
    handles = [Line2D([], [], color=SERIES[i], marker="o", ms=5, mec=SURFACE, label=f"p95, {RAMP[p]}")
               for i, p in enumerate(RAMP) if any(r.phase == p for r in used)]
    handles += [
        Line2D([], [], color=MUTED, lw=6, alpha=0.3, label="p50–p99 band"),
        Line2D([], [], ls="", marker="D", ms=8, mfc=SURFACE, mec=INK2, mew=1.5, label="degradation onset (p95 ≥ 2× first step)"),
        Line2D([], [], ls="", marker="X", ms=9, color=INK2, label="breaking point (p95 > 10 s, >1% errors, any 504 or drop)"),
    ]
    if any(r.meta.get("predicted_breaking_per_min") for r in used):
        handles.append(Line2D([], [], color=INK2, lw=1, ls=(0, (2, 2)), label="predicted breaking point"))
    _legend(axes[-1][0], handles=handles, ncol=2)
    _save(fig, out_dir, 2, "ramp-latency", used, written)


def fig_ramp_errors(ramps, out_dir, written):
    from matplotlib.ticker import MaxNLocator
    models = sorted({r.model for r, _ in ramps})
    rows = [("error_rate", "Failed checks (%)", 100), ("n504", "504 responses", 1), ("dropped", "Dropped iterations", 1)]
    fig, axes = _fig("Phase 3 · Failed checks, 504s and dropped arrivals per ramp step",
                     3, len(models), h=6.4, sharex="col")
    used = []
    for col, model in enumerate(models):
        for slot, phase in enumerate(RAMP):
            hit = ramp_pick(ramps, model, phase)
            if not hit:
                continue
            run, steps = hit
            used.append(run)
            xs = [s["rate_per_min"] for s in steps]
            for row, (key, _, scale) in enumerate(rows):
                axes[row][col].plot(xs, [(s[key] or 0) * scale for s in steps], color=SERIES[slot],
                                    marker="o", ms=5, mec=SURFACE, mew=1.2, label=RAMP[phase])
        for row, (_, label, _) in enumerate(rows):
            ax = axes[row][col]
            ax.set_ylim(bottom=0, top=max(1, ax.get_ylim()[1]))
            ax.yaxis.set_major_locator(MaxNLocator(integer=row > 0, nbins=4))
            ax.set_ylabel(label if col == 0 else "")
        axes[0][col].axhline(ERR_LIMIT * 100, color=CRITICAL, lw=1)
        axes[0][col].set_title(name(model))
        axes[-1][col].set_xlabel("Offered rate (req/min)")
    handles, labels = axes[0][0].get_legend_handles_labels()
    _legend(axes[-1][0], handles=handles, labels=labels, ncol=2, title="Red line: 1% error limit")
    _save(fig, out_dir, 3, "ramp-errors", used, written)


def fig_headline(heads, out_dir, written):
    models = sorted({r.model for r, _ in heads})
    fig, axes = _fig("Phase 4 · Single-check latency at the headline rate, idle vs. while a batch drains",
                     1, len(models), h=3.8, sharey=True)
    keys = [("p50_ms", "p50"), ("p95_ms", "p95"), ("p99_ms", "p99")]
    w = 0.36
    for ax, model in zip(axes[0], models):
        for slot, phase in enumerate(HEAD):
            got = [st for r, st in heads if r.model == model and r.phase == phase]
            if not got:
                continue
            for i, (k, _) in enumerate(keys):
                vals = [st[k] for st in got if st[k] is not None]
                if not vals:
                    continue
                x = i + (slot - 0.5) * w
                med = statistics.median(vals)
                ax.bar(x, med, width=w * 0.9, color=SERIES[slot], label=f"{HEAD[phase]} (n={len(got)} runs)" if i == 0 else None)
                if len(vals) > 1:
                    _dots(ax, [x] * len(vals), vals, INK2, size=10)
                ax.annotate(f"{med:,.0f}", (x, med), xytext=(0, 2), textcoords="offset points",
                            ha="center", va="bottom", fontsize=7, color=INK2)
        ax.set_xticks(range(len(keys)), [lab for _, lab in keys])
        ax.set_title(name(model))
        _ms_axis(ax)
        _limit_line(ax)
        ax.set_ylim(0, max(P95_LIMIT_MS * 1.1, ax.get_ylim()[1]))
    for ax in axes[0][1:]:
        ax.set_ylabel("")
    h, lab = axes[0][0].get_legend_handles_labels()
    _legend(axes[-1][0], handles=h, labels=lab, ncol=2, title="Bars: median across runs · dots: each run")
    _save(fig, out_dir, 4, "headline", [r for r, _ in heads], written)


def _check_points(run, t_ref):
    pts = {"ok": ([], []), "504": ([], []), "other": ([], [])}
    for r in measured(run.rows):
        if r["metric"] == "http_req_duration" and r["kind"] == "check":
            key = "ok" if r["status"] == "201" else "504" if r["status"] == "504" else "other"
            pts[key][0].append((r["ts"] - t_ref) / 1000)
            pts[key][1].append(r["value"])
    return pts


def _batch_markers(ax, run, label=True):
    ax.axvline(0, color=INK2, lw=1)
    d = run.drain_s()
    if d is not None:
        ax.axvline(d, color=INK2, lw=1)
    if label:
        # Headroom above the data, two label rows so the labels never overlap each other.
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi + (hi - lo) * 0.18)
        trans = ("data", "axes fraction")
        ax.annotate("batch submitted", (0, 1), xycoords=trans, xytext=(3, -2), textcoords="offset points",
                    va="top", fontsize=7.5, color=INK2)
        if d is not None:
            ax.annotate(f"batch drained ({d:,.0f} s)", (d, 1), xycoords=trans, xytext=(3, -13),
                        textcoords="offset points", va="top", fontsize=7.5, color=INK2)


def fig_timeline(loaded, out_dir, written):
    fig, axes = _fig("Phase 4 · Every single check while a 500-row batch drains",
                     len(loaded), 1, h=1.2 + 2.6 * len(loaded))
    for ax, run in zip(axes[:, 0], loaded):
        pts = _check_points(run, run.t_ref())
        _dots(ax, *pts["ok"], SERIES[0], "201 (scored)")
        _dots(ax, *pts["504"], CRITICAL, "504 (detector timeout)", marker="s", size=14)
        _dots(ax, *pts["other"], MUTED, "other error", marker="x", size=14)
        _batch_markers(ax, run)
        _limit_line(ax)
        _ms_axis(ax)
        ax.set_ylim(0, max(P95_LIMIT_MS * 1.15, ax.get_ylim()[1]))
        ax.set_title(f"{name(run.model)} · {run.meta.get('rate_per_min')} req/min")
        ax.set_xlabel("Time since batch submission (s)")
    h, lab = axes[0][0].get_legend_handles_labels()
    _legend(axes[-1][0], handles=h, labels=lab, ncol=3, markerscale=2)
    _save(fig, out_dir, 5, "loaded-timeline", loaded, written)


def fig_resources(loaded, out_dir, written):
    containers = ["detector", "worker", "api"]
    fig, axes = _fig("Phase 4 · Container CPU and memory while a 500-row batch drains",
                     2, len(loaded), h=5.0, sharex="col")
    for col, run in enumerate(loaded):
        t_ref, stats = run.t_ref(), run.stats
        for slot, ctr in enumerate(containers):
            s = [x for x in stats if x["name"] == ctr]
            if not s:
                continue
            t = [(x["t"] - t_ref) / 1000 for x in s]
            axes[0][col].plot(t, [x["cpu"] for x in s], color=SERIES[slot], lw=1.5, label=ctr)
            axes[1][col].plot(t, [x["mem"] for x in s], color=SERIES[slot], lw=1.5, label=ctr)
        for row in (0, 1):
            _batch_markers(axes[row][col], run, label=row == 0)
            axes[row][col].set_ylim(bottom=0)
        axes[0][col].set_title(name(run.model))
        axes[0][col].set_ylabel("CPU (% of one core)" if col == 0 else "")
        axes[1][col].set_ylabel("Memory (GiB)" if col == 0 else "")
        axes[1][col].set_xlabel("Time since batch submission (s)")
    h, lab = axes[0][0].get_legend_handles_labels()
    _legend(axes[-1][0], handles=h, labels=lab, ncol=3,
               title="CPU 100% = one core; the detector is limited to 2 cores (200%)", title_fontsize=7.5)
    _save(fig, out_dir, 6, "resources", loaded, written)


def health(run):
    """/health probe durations split into (ok, failed) rows; a failed probe's time isn't latency."""
    rows = [r for r in run.rows if r["metric"] == "http_req_duration" and r["kind"] == "health"]
    return [r for r in rows if r["status"] == "200"], [r for r in rows if r["status"] != "200"]


def freeze_pick(freezes):
    """(model, [newest sync run, newest async run]) for one model: desklib if it has both
    variants, else any model that has both, else whatever exists for one model."""
    by = {}
    for r in freezes:  # sorted by run id = time, so the newest of each variant wins
        by.setdefault(r.model, {})[r.meta.get("variant")] = r
    full = sorted(m for m in by if {"sync", "async"} <= set(by[m]))
    model = "desklib" if "desklib" in (full or by) else (full or sorted(by))[0]
    return model, [by[model][v] for v in ("sync", "async") if v in by[model]]


def fig_freeze(freezes, out_dir, written):
    _, picks = freeze_pick(freezes)
    names = {"sync": "before fix (create_batch on the event loop)", "async": "after fix (boto3 off the event loop)"}
    fig, axes = _fig("Phases 5–6 · Does submitting a 500-row batch stall other requests?",
                     len(picks), 1, h=1.2 + 2.6 * len(picks), sharex=True, sharey=True)
    for ax, run in zip(axes[:, 0], picks):
        t_ref = run.t_ref()
        pts = _check_points(run, t_ref)
        h_ok, h_fail = health(run)
        sub = run.submit_ms()
        if sub:
            ax.axvspan(0, sub / 1000, color=CRITICAL, alpha=0.12, lw=0)
            ax.annotate(f"POST /api/batches in flight: {sub:,.0f} ms", (sub / 1000, 1), xycoords=("data", "axes fraction"),
                        xytext=(4, -2), textcoords="offset points", va="top", fontsize=7.5, color=INK2)
        _dots(ax, *pts["ok"], SERIES[0], "single check (201)")
        _dots(ax, [(r["ts"] - t_ref) / 1000 for r in h_ok], [r["value"] for r in h_ok], SERIES[1], "GET /health probe (200)")
        _dots(ax, [(r["ts"] - t_ref) / 1000 for r in h_fail], [max(r["value"], 1) for r in h_fail], CRITICAL,
              "failed /health probe", marker="x", size=18)
        _dots(ax, *pts["504"], CRITICAL, "504", marker="s", size=14)
        if h_ok or h_fail:  # zoom to the /health probe window: the freeze is seconds wide, the run minutes
            hx = [(r["ts"] - t_ref) / 1000 for r in h_ok + h_fail]
            ax.set_xlim(min(hx) - 2, max(hx) + 2)
        _ms_axis(ax, log=True)
        ax.set_title(f"{names[run.meta.get('variant')]} · {name(run.model)}")
    axes[-1][0].set_xlabel("Time since batch submission (s)")
    h, lab = axes[0][0].get_legend_handles_labels()
    _legend(axes[-1][0], handles=h, labels=lab, ncol=3, markerscale=2)
    _save(fig, out_dir, 7, "freeze", picks, written)


def fig_models(cmp, out_dir, written):
    """cmp: {model: {metric: value | None}}, metrics in CMP order."""
    models = sorted(cmp)
    fig, axes = _fig("Model comparison · same host, same workload", 1, len(CMP), w=9, h=3.2)
    for ax, (key, label) in zip(axes[0], CMP):
        for i, m in enumerate(models):
            v = cmp[m].get(key)
            if v is None:
                ax.annotate(cmp[m].get(key + "_note", "n/a"),(i, 0), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.5, color=MUTED)
                continue
            ax.bar(i, v, width=0.5, color=SERIES[0])
            ax.annotate(f"{v:,.1f}" if v < 10 else f"{v:,.0f}", (i, v), xytext=(0, 2),
                        textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK2)
        ax.set_xticks(range(len(models)), [name(m).replace(" (", "\n(") for m in models], fontsize=7.5)
        ax.set_title(label, fontsize=8, fontweight="bold", wrap=True)
        ax.margins(x=0.25)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.12)  # headroom for the value labels
    _save(fig, out_dir, 8, "model-comparison", [r for runs in cmp.values() for r in runs["_runs"]], written)


CMP = [("capacity", "Capacity 60/S\n(req/min)"), ("break_idle", "Breaking point,\nidle (req/min)"),
       ("break_batch", "Breaking point,\nunder batch (req/min)"), ("head_p95", "Headline p95,\nloaded (ms)"),
       ("peak_mem", "Peak detector\nmemory (GiB)")]


# ---- RESULTS.md -----------------------------------------------------------------------


def f_ms(v):
    return "—" if v is None else f"{v:,.0f}"


def f_pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def hand(name, prompt):
    return f"<!-- hand:{name} -->\n_TODO: {prompt}_\n<!-- /hand:{name} -->"


def fig_link(n, written):
    return f"![Figure {n}: {FIGS[n]}]({written[n]})" if n in written else f"_Figure {n} ({FIGS[n]}): not yet run._"


LIMITATIONS = """- **Local ≠ AWS.** The stack runs on one laptop under Docker Desktop. Containers get the ECS
  CPU *counts* (detector 2, api 0.5, worker 0.25) but not Fargate's CPU *speed*, and k6 shares the
  host with the system under test (pinned to its own core). Absolute numbers transfer only
  roughly; the shape of the curves and the relative effects are the result.
- **tmpfs Postgres.** The database lives in memory and starts empty each run, so disk I/O and
  table growth are not part of the measurement.
- **Short-answer workload.** Answers come from the project's short-answer corpus. Longer
  answers cost the detector more per check, so capacity for long answers will be lower.
- **LocalStack latency.** S3 and SQS are LocalStack on the same Docker network (~1 ms per call);
  real SQS costs tens of ms per call, so the `create_batch` freeze is expected to be larger on
  AWS than measured here."""


def method(runs):
    """Method section from the charted runs only; "—" until there are some."""
    metas = [r.meta for r in runs] or [{}]
    distinct = lambda f: ", ".join(sorted({str(f(m)) for m in metas if f(m) is not None})) or "—"
    host = lambda m: m.get("host") and "{}, {} logical CPUs, {}".format(
        *(m["host"].get(k, "?") for k in ("cpu_model", "ncpu", "os")))
    dmem = lambda m: (m.get("host") or {}).get("docker_mem_bytes") and f"{m['host']['docker_mem_bytes'] / 2**30:.1f} GiB"
    per_key = {}  # limit -> value -> models, so differing configs stay readable
    for r in runs:
        for k, v in (r.meta.get("limits") or {}).items():
            per_key.setdefault(k, {}).setdefault("null" if v is None else str(v), set()).add(name(r.model))
    limits = "; ".join(
        f"{k}=" + (next(iter(vals)) if len(vals) == 1
                   else ", ".join(f"{v} ({'/'.join(sorted(ms))})" for v, ms in sorted(vals.items())))
        for k, vals in per_key.items()) or "—"
    none_yet = "" if runs else "\n\n_No charted runs yet: the run-specific values below fill in once there are._\n"
    sha = lambda m: m.get("git_sha") and m["git_sha"][:7] + (" (dirty)" if m.get("git_dirty") else "")
    return f"""## Method

- **Stack.** Disposable Docker Compose project `prompt-patrol-loadtest` (`docker-compose.yml`): api,
  worker, detector, Postgres on tmpfs, LocalStack for S3/SQS. A fresh stack (empty DB and
  queue) per run, torn down with `down -v`. Requests authenticate with a seeded session, so
  Auth0 is not on the measured path (every request is a DB session lookup, as in production).{none_yet}
- **Container limits** (from `meta.json`): {limits}.
- **Host:** {distinct(host)}; Docker memory {distinct(dmem)}.
- **Load generator:** k6 {distinct(lambda m: m.get("k6_version"))}, open workload model (arrival-rate
  executors), so a slow server cannot slow the arrivals down.
- **Code under test:** git {distinct(sha)}.
- **Workload.** `POST /api/checks` with a random short answer (strictness `standard`). Each run
  starts with 20 serial warm-up checks that are excluded from every number. Latency figures use
  successful checks only (201 with a verdict) so a fast error never looks like good latency;
  failures count in the error rate. Phases: 1 calibrate (100 serial checks, S = median),
  3 stepped ramp at 0.1–1.25 × 60/S req/min (2 min plateaus, idle and under 500-row batches),
  4 headline constant rate (idle 10 min; loaded until one 500-row batch drains), 5–6 batch
  submission freeze before/after the `create_batch` fix.
"""


def render_md(charted, excluded, not_charted, data, written):
    cal, ramps, heads, freezes = data["cal"], data["ramps"], data["heads"], data["freezes"]
    out = ["# PP-533 load test — results", "",
           "_Generated by `render.py` from `results/`. Edit only inside `<!-- hand:… -->` blocks; "
           "everything else is rewritten on every render (`run.sh render`)._", "",
           method(charted),
           "## Prediction (Phase 2)", "",
           hand("prediction", "expected degradation onset and breaking point, idle and under batch, written before Phase 3 ran."),
           "", "## Results", "", "### Phase 1 — calibration", ""]
    if cal:
        rows = []
        for r in cal:
            st = check_stats(measured(r.rows))
            rows.append([name(r.model), f"`{r.id}`", st["n_ok"], f_ms(st["p50_ms"]),
                         f_ms(st["p95_ms"]), f_ms(st["p99_ms"]), r.meta.get("service_time_s", "—"),
                         f"{60 / st['p50_ms'] * 1000:,.0f}" if st["p50_ms"] else "—"])
        out += [table(["Model", "Run", "OK checks", "p50 ms", "p95 ms", "p99 ms", "S (s, from k6)", "Capacity 60/S (req/min)"], rows), ""]
    out += [fig_link(1, written), "", "### Phase 3 — stepped ramp", "",
            "_Achieved req/min is completion throughput (k6 stamps each request when it completes), "
            "not the arrival rate: under overload it falls below the offered rate._", ""]
    for r, steps in ramps:
        pts = find_points(steps)
        out += [f"**{name(r.model)}, {RAMP[r.phase]}** (`{r.id}`): onset "
                f"{pts['onset'] or 'not reached'} req/min, breaking point {pts['breaking'] or 'not reached'} req/min"
                + (f" (predicted {r.meta['predicted_breaking_per_min']})" if r.meta.get("predicted_breaking_per_min") else "")
                + ".", ""]
        rows = [[s["rate_per_min"], f"{s['achieved_per_min']:.1f}" if s["achieved_per_min"] else "—",
                 f_ms(s["p50_ms"]), f_ms(s["p95_ms"]), f_ms(s["p99_ms"]), f_pct(s["error_rate"]),
                 s["n504"], s["dropped"],
                 " ".join(lab for lab, k in (("onset", "onset"), ("**breaking**", "breaking"))
                          if pts[k] == s["rate_per_min"])] for s in steps]
        out += [table(["Offered req/min", "Achieved req/min (completions)", "p50 ms", "p95 ms", "p99 ms", "Errors", "504", "Dropped", "Marker"], rows), ""]
    out += [fig_link(2, written), "", fig_link(3, written), "", "### Phase 4 rate choice", "",
            hand("rate-choice", "which headline rates were chosen from the Phase 3 breaking points, and why."),
            "", "### Phase 4 — headline", ""]
    groups = {}
    for r, st in heads:
        groups.setdefault((r.model, r.phase), []).append((r, st))
    if groups:
        rows = []
        for (model, phase), got in sorted(groups.items()):
            def med(k):
                vals = [st[k] for _, st in got if st[k] is not None]
                return statistics.median(vals) if vals else None
            drains = [r.drain_s() for r, _ in got if r.drain_s() is not None]
            rows.append([name(model), HEAD[phase], len(got),
                         ", ".join(sorted({str(r.meta.get("rate_per_min")) for r, _ in got})),
                         f_ms(med("p50_ms")), f_ms(med("p95_ms")), f_ms(med("p99_ms")), f_pct(med("error_rate")),
                         sum(st["n504"] for _, st in got), sum(st["dropped"] for _, st in got),
                         ", ".join(f"{d:,.0f}" for d in drains) or "—"])
        out += ["Percentiles and error rate: median across runs. 504s and dropped: totals across runs.", "",
                table(["Model", "Condition", "Runs", "Rate (req/min)", "p50 ms", "p95 ms", "p99 ms", "Errors",
                       "504", "Dropped", "Batch drain (s)"], rows), ""]
    out += [fig_link(4, written), "", fig_link(5, written), "", fig_link(6, written), "",
            "### Phases 5–6 — `create_batch` freeze", ""]
    if freezes:
        rows = []
        for r in freezes:
            st = check_stats(measured(r.rows))
            h_ok, h_fail = health(r)
            hp = [x["value"] for x in h_ok]
            rows.append([f"`{r.id}`", name(r.model), r.meta.get("variant", "?"),
                         f_ms(r.submit_ms()), f_ms(pct(hp, 95)), f_ms(max(hp) if hp else None), len(h_fail),
                         f_ms(st["p95_ms"]), st["n504"],
                         f"{r.drain_s():,.0f}" if r.drain_s() is not None else "—"])
        out += [table(["Run", "Model", "Variant", "POST /api/batches ms (freeze)", "/health p95 ms",
                       "/health max ms", "Failed /health", "Check p95 ms", "504", "Batch drain (s)"], rows), ""]
    if 7 in written:
        model, picks = freeze_pick(freezes)
        missing = [v for v in ("sync", "async") if v not in {r.meta.get("variant") for r in picks}]
        out += [f"_Figure 7 shows {name(model)} only (one model, so before/after compare like with like)"
                + (f"; no {' or '.join(missing)} run yet" if missing else "") + "._", ""]
    out += [fig_link(7, written), "", "### Model comparison", "", fig_link(8, written) if 8 in written
            else "_Figure 8 (model comparison): needs charted runs of both models; not yet run._", "",
            "## Discussion", "",
            hand("discussion", "what the numbers say: onset vs. prediction, batch impact, freeze, surprises."),
            "", "## AC4 verdict", "", ac4_table(groups), "",
            hand("verdict", "PASS/FAIL per model and the fix the team would choose if it fails."),
            "", "## Limitations", "", LIMITATIONS, "", "## Runs not charted", ""]
    out += [f"- `{r.id}`: {why}" for r, why in not_charted] or ["_None._"]
    out += ["", "## Excluded runs", ""]
    out += [table(["Run", "Phase", "Status", "Reason"],
                  [[f"`{r.id}`", r.phase, r.status, r.meta.get("status_reason") or "—"] for r in excluded])
            if excluded else "_None._", ""]
    return "\n".join(out)


def ac4_table(groups):
    if not groups:
        return "_No headline runs yet: the AC4 threshold table appears once Phase 4 has run._"
    rows = []
    mark = lambda ok: "PASS" if ok else "**FAIL**"
    for (model, phase), got in sorted(groups.items()):
        p95s = [st["p95_ms"] for _, st in got if st["p95_ms"] is not None]
        p95 = statistics.median(p95s) if p95s else None
        n504 = sum(st["n504"] for _, st in got)
        n = sum(st["n"] for _, st in got)
        ok = sum(st["n_ok"] for _, st in got)  # checks.ts adds one check_ok_duration per successful check
        succ = ok / n if n else None
        dropped = sum(st["dropped"] for _, st in got)
        rows.append([name(model), HEAD[phase], len(got),
                     f"{f_ms(p95)} {mark(p95 is not None and p95 < P95_LIMIT_MS)}",
                     f"{n504} {mark(n504 == 0)}", f"{f_pct(succ)} {mark(succ is not None and succ > 0.99)}",
                     f"{dropped} {mark(dropped == 0)}"])
    return ("Thresholds: p95 < 10,000 ms (median of runs), 504 = 0, check success > 99% (pooled), "
            "dropped iterations = 0 (totals across runs).\n\n"
            + table(["Model", "Condition", "Runs", "p95 ms", "504", "Check success", "Dropped"], rows))


# ---- main ---------------------------------------------------------------------------------


def main(results_dir=HERE / "results", out_dir=HERE, include_stub=False):
    results_dir, out_dir = Path(results_dir), Path(out_dir)
    charted, excluded, not_charted = [], [], []
    dirs = sorted(d for d in results_dir.iterdir() if d.is_dir() and not d.name.startswith("_")) if results_dir.exists() else []
    for d in dirs:
        r = Run(d)
        if r.phase == "smoke":
            not_charted.append((r, "smoke test (plumbing check, never charted)"))
        elif r.status != "ok":
            excluded.append(r)
        elif not include_stub and (r.meta.get("detector") == "stub" or r.meta.get("quick")):
            why = "stub detector" if r.meta.get("detector") == "stub" else "quick run (timings ÷10)"
            not_charted.append((r, f"{why}, harness dry-run ({r.phase})"))
        else:
            charted.append(r)

    data = {
        "cal": [r for r in charted if r.phase == "calibrate"],
        "ramps": [(r, step_stats(r.rows, r.meta.get("steps_per_min") or [])) for r in charted if r.phase in RAMP],
        "heads": [(r, check_stats(measured(r.rows))) for r in charted if r.phase in HEAD],
        "freezes": [r for r in charted if r.phase == "freeze"],
    }
    data["ramps"] = [(r, st) for r, st in data["ramps"] if st]
    written = {}
    fig_dir = out_dir / "figures"
    for old in fig_dir.glob("[0-9]-*.*") if fig_dir.exists() else []:
        old.unlink()  # a figure whose inputs vanished must not linger
    cal = [r for r in data["cal"] if any(x["metric"] == "check_ok_duration" for x in measured(r.rows))]
    if cal:
        fig_calibration(cal, out_dir, written)
    if data["ramps"]:
        fig_ramp(data["ramps"], out_dir, written)
        fig_ramp_errors(data["ramps"], out_dir, written)
    if data["heads"]:
        fig_headline(data["heads"], out_dir, written)
    loaded = [newest([r for r, _ in data["heads"]], model=m, phase="headline-loaded")
              for m in sorted({r.model for r, _ in data["heads"]})]
    loaded = [r for r in loaded if r]
    if loaded:
        fig_timeline(loaded, out_dir, written)
        if any(r.stats for r in loaded):
            fig_resources(loaded, out_dir, written)
    if data["freezes"]:
        fig_freeze(data["freezes"], out_dir, written)
    cmp = model_comparison(charted, data)
    if {"baseline", "desklib"} <= set(cmp):
        fig_models({m: cmp[m] for m in ("baseline", "desklib")}, out_dir, written)

    md_path = out_dir / "RESULTS.md"
    new = render_md(charted, excluded, not_charted, data, written)
    if md_path.exists():
        new = merge_hand_blocks(md_path.read_text(encoding="utf-8"), new)
    md_path.write_text(new, encoding="utf-8", newline="\n")
    print(f"render.py: {len(charted)} charted, {len(not_charted)} not charted, {len(excluded)} excluded; "
          f"figures: {sorted(written) or 'none'}")


def model_comparison(charted, data):
    cmp = {}
    for m in {r.model for r in charted}:
        used = []  # only the runs that feed a bar, for the footnote
        cal = newest(data["cal"], model=m)
        med = cal and pct([x["value"] for x in measured(cal.rows) if x["metric"] == "check_ok_duration"], 50)
        c = {"capacity": 60000 / med if med else None}
        used += [cal] if med else []
        for key, phase in (("break_idle", "ramp-idle"), ("break_batch", "ramp-batch")):
            hit = ramp_pick(data["ramps"], m, phase)
            c[key] = find_points(hit[1])["breaking"] if hit else None
            if hit:
                used.append(hit[0])
                if c[key] is None:
                    c[key + "_note"] = "not reached"
        loaded = [(r, st["p95_ms"]) for r, st in data["heads"]
                  if r.model == m and r.phase == "headline-loaded" and st["p95_ms"]]
        c["head_p95"] = statistics.median(v for _, v in loaded) if loaded else None
        used += [r for r, _ in loaded]
        mem = [(r.peak_detector_gib(), r) for r in charted if r.model == m and r.peak_detector_gib()]
        c["peak_mem"], peak_run = max(mem, key=lambda x: x[0]) if mem else (None, None)
        used += [peak_run] if peak_run else []
        c["_runs"] = list(dict.fromkeys(used))
        cmp[m] = c
    return cmp


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--include-stub", action="store_true",
                    help="also chart stub-detector and quick runs (harness dry-runs only, never for the report)")
    main(include_stub=ap.parse_args().include_stub)
