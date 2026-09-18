"""Build mixed-authorship documents from human and AI answers.

Each document starts from an eligible human answer. k of its n sentences
are replaced, at their original positions, with sentences from one AI
answer to the same question. Every sentence carries a human or ai label,
the document records both source answer ids, and the target and actual
AI fractions. Deterministic for a fixed config and seed.
"""

import random
import re

from splicer.segment import segment

# signals from docs/segmentation_review_v3.md: code fragments, notation
# lists and ellipsis-heavy answers make bad splice donors
_CODE = re.compile(r"[{};]|//|==|\[\]|\+\+")
_ELLIPSES = re.compile(r"\.\.\.")


def is_eligible(sentences: list[str], min_sentences: int) -> bool:
    """A donor answer must be prose with enough sentences, no code
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


def splice_pair(human_sentences, ai_sentences, target_fraction, rng):
    """Replace positions in the human answer with AI sentences.

    Returns (labelled_sentences, actual_fraction). k is clamped so the
    result always mixes both authors. Returns None when the AI answer
    has too few sentences to fill the chosen positions.
    """
    n = len(human_sentences)
    k = max(1, min(n - 1, round(target_fraction * n)))
    if len(ai_sentences) < k:
        return None
    positions = sorted(rng.sample(range(n), k))
    replacements = ai_sentences[:k]
    labelled = []
    replaced = 0
    for i, sentence in enumerate(human_sentences):
        if i in positions:
            labelled.append({"text": replacements[replaced], "label": "ai"})
            replaced += 1
        else:
            labelled.append({"text": sentence, "label": "human"})
    return labelled, k / n


def make_rng(seed: int) -> random.Random:
    """A private generator, so determinism cannot be broken by other code
    touching the global random state."""
    return random.Random(seed)
