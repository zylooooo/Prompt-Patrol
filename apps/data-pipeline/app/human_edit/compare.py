"""Compare genuine and simulated edits on how much text changed.

The measure is word-level edit distance between each edited answer and its
source (see common.word_edit_distance). The output is a JSON summary plus a
markdown section to paste into the dataset card, so a reader can judge how
faithful the simulation is.
"""

import argparse
import bisect
import json
import logging
import statistics
from pathlib import Path

from human_edit.common import DATA_DIR, read_jsonl, word_edit_distance

logger = logging.getLogger(__name__)

BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0]


def distances(records):
    return [word_edit_distance(r["source_answer"], r["answer"]) for r in records]


def quantile(sorted_values, q):
    index = min(len(sorted_values) - 1, round(q * (len(sorted_values) - 1)))
    return sorted_values[index]


def summarise(values):
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": round(statistics.fmean(ordered), 4),
        "p25": round(quantile(ordered, 0.25), 4),
        "median": round(quantile(ordered, 0.5), 4),
        "p75": round(quantile(ordered, 0.75), 4),
        "p90": round(quantile(ordered, 0.9), 4),
    }


def histogram(values):
    """Share of values in each bin, the last bin closed on the right."""
    shares = []
    for low, high in zip(BINS, BINS[1:], strict=False):
        last = high == BINS[-1]
        count = sum(low <= v < high or (last and v == high) for v in values)
        shares.append({"range": f"{low:.1f}-{high:.1f}", "share": round(count / len(values), 4)})
    return shares


def ks_statistic(a, b):
    """Two-sample Kolmogorov-Smirnov statistic: the largest gap between the
    two cumulative distributions. 0 means identical, 1 means no overlap."""
    a, b = sorted(a), sorted(b)
    return round(max(
        abs(bisect.bisect_right(a, v) / len(a) - bisect.bisect_right(b, v) / len(b)) for v in a + b
    ), 4)


def compare(genuine, simulated):
    if not genuine or not simulated:
        raise SystemExit("both genuine and simulated edits are needed for the comparison")
    g, s = distances(genuine), distances(simulated)
    return {
        "measure": "word-level edit distance to the source answer, 0 identical, 1 nothing in common",
        "genuine": {**summarise(g), "histogram": histogram(g)},
        "simulated": {**summarise(s), "histogram": histogram(s)},
        "ks_statistic": ks_statistic(g, s),
    }


def to_markdown(result):
    g, s = result["genuine"], result["simulated"]
    lines = [
        "## Genuine vs simulated edits",
        "",
        f"Measure: {result['measure']}.",
        "",
        "| | n | mean | p25 | median | p75 | p90 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, row in (("genuine", g), ("simulated", s)):
        lines.append(f"| {name} | {row['n']} | {row['mean']} | {row['p25']} | {row['median']} | "
                     f"{row['p75']} | {row['p90']} |")
    lines += ["", "| edit distance | genuine | simulated |", "|---|---|---|"]
    for gb, sb in zip(g["histogram"], s["histogram"], strict=True):
        lines.append(f"| {gb['range']} | {gb['share']:.0%} | {sb['share']:.0%} |")
    lines += [
        "",
        f"Kolmogorov-Smirnov statistic: {result['ks_statistic']} (0 means the two "
        "distributions match, 1 means they do not overlap).",
        "",
    ]
    return "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Compare genuine and simulated edit distances.")
    parser.add_argument("--genuine", default=DATA_DIR / "genuine.jsonl")
    parser.add_argument("--run", required=True, help="simulated run folder holding simulated.jsonl")
    args = parser.parse_args()

    run_dir = Path(args.run)
    result = compare(read_jsonl(args.genuine), read_jsonl(run_dir / "simulated.jsonl"))
    (run_dir / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (run_dir / "comparison.md").write_text(to_markdown(result), encoding="utf-8")
    logger.info("genuine median %s, simulated median %s, KS %s",
                result["genuine"]["median"], result["simulated"]["median"], result["ks_statistic"])


if __name__ == "__main__":
    main()
