"""Splice primitives for spliced answers: base eligibility, replacement, AI share and bands.

A spliced answer starts from an eligible student answer. Sentences at
chosen positions are replaced, in order, by the first sentences of an AI
answer to the same question. Every sentence keeps its author, and the AI
share counts words with the corpus word rule. Deterministic for a fixed
seed.
"""

import itertools
import math
import random
import re

from harness.generate import count_words

# signals from docs/segmentation_review_v3.md: code fragments, notation
# lists and ellipsis-heavy answers make bad splice bases
_CODE = re.compile(r"[{};]|//|==|\[\]|\+\+")
_ELLIPSES = re.compile(r"\.\.\.")


def is_eligible(sentences: list[str], min_sentences: int) -> bool:
    """A base human answer must be prose with enough sentences, no code
    fragments, few ellipses and mostly full-length sentences."""
    if len(sentences) < min_sentences:
        return False
    if any(_CODE.search(s) for s in sentences):
        return False
    if sum(len(_ELLIPSES.findall(s)) for s in sentences) >= 3:
        return False
    short = sum(1 for s in sentences if len(s.split()) < 4)
    if short / len(sentences) > 0.5:
        return False
    return True


def splice_at(human_sentences, ai_sentences, positions):
    """The human sentences with those at positions replaced, in order, by
    the first len(positions) AI sentences. A prefix rather than a sample,
    shuffled sentences read incoherently."""
    chosen = set(positions)
    donor = iter(ai_sentences[:len(chosen)])
    return [
        {"text": next(donor), "label": "ai"} if i in chosen else {"text": sentence, "label": "human"}
        for i, sentence in enumerate(human_sentences)
    ]


def ai_share(labelled):
    """Share of the words that are AI, by the corpus word rule."""
    ai = sum(count_words(s["text"]) for s in labelled if s["label"] == "ai")
    total = sum(count_words(s["text"]) for s in labelled)
    return ai / total if total else 0.0


def band_of(share, bands):
    """The band whose closed range holds share, or None between bands."""
    for band, (low, high) in sorted(bands.items()):
        if low <= share <= high:
            return band
    return None


def position_sets(n, k, rng, cap):
    """Every set of k positions out of n, or cap distinct sets drawn with
    rng when there are more, so a long answer stays cheap."""
    if math.comb(n, k) <= cap:
        return list(itertools.combinations(range(n), k))
    drawn = set()
    while len(drawn) < cap:
        drawn.add(tuple(sorted(rng.sample(range(n), k))))
    return sorted(drawn)


def band_candidates(base_id, base_sentences, donor_id, donor_sentences, bands, seed, cap):
    """One splice per band this base and donor can reach, as band to
    (positions, labelled sentences, share). Position draws are seeded per
    pair and the pick within a band per pair and band, so the result does
    not depend on the order pairs are visited."""
    n = len(base_sentences)
    human_words = [count_words(s) for s in base_sentences]
    ai_words = [count_words(s) for s in donor_sentences]
    total = sum(human_words)
    draw = random.Random(f"{seed}/positions/{base_id}/{donor_id}")
    reached = {}
    for k in range(1, min(n - 1, len(donor_sentences)) + 1):
        added = sum(ai_words[:k])
        for positions in position_sets(n, k, draw, cap):
            share = added / (added + total - sum(human_words[p] for p in positions))
            band = band_of(share, bands)
            if band is not None:
                reached.setdefault(band, []).append((positions, share))
    picked = {}
    for band, options in sorted(reached.items()):
        positions, share = random.Random(f"{seed}/{band}/{base_id}/{donor_id}").choice(options)
        picked[band] = (positions, splice_at(base_sentences, donor_sentences, positions), share)
    return picked


def make_rng(seed: int) -> random.Random:
    """A private generator, so determinism cannot be broken by other code
    touching the global random state."""
    return random.Random(seed)
