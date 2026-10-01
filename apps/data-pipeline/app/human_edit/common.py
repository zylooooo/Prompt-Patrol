"""Shared helpers for the human-edited answer set."""

import json
import logging
import random
import re
from pathlib import Path

import yaml

from harness.prompts import is_rewrite

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"
DATA_DIR = PIPELINE_DIR / "data" / "human_edit"

TOKEN = re.compile(r"\w+")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def load_answers(path):
    """Harness records with a non-empty answer, in file order.
    Rewrite-tier records are skipped."""
    records = read_jsonl(path)
    rewrites = sum(is_rewrite(r) for r in records)
    if rewrites:
        logger.info("%d rewrite-tier records skipped", rewrites)
    return [r for r in records if r.get("answer", "").strip() and not is_rewrite(r)]


def normalise(text):
    """Whitespace-insensitive form, to tell an untouched row from an edit."""
    return " ".join(text.split())


def tokens(text):
    return TOKEN.findall(text.lower())


def word_edit_distance(source, edited):
    """Word-level Levenshtein distance divided by the longer length, so 0
    means identical and 1 means nothing in common. Case and punctuation
    are ignored."""
    a, b = tokens(source), tokens(edited)
    if not a and not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, word_a in enumerate(a, 1):
        current = [i]
        for j, word_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word_a != word_b)))
        previous = current
    return previous[-1] / max(len(a), len(b))


def stratified_sample(answers, share, seed):
    """A fixed share of answers from every (generator, tier) group, so the
    set covers all generators and quality tiers. Same inputs, same pick."""
    if not 0 < share <= 1:
        raise SystemExit(f"share must be in (0, 1], got {share}")
    groups = {}
    for record in answers:
        groups.setdefault((record["generator"], record["tier"]), []).append(record)
    rng = random.Random(seed)
    picked = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda r: r["answer_id"])
        count = min(len(group), max(1, round(len(group) * share)))
        picked.extend(rng.sample(group, count))
    return sorted(picked, key=lambda r: r["answer_id"])
