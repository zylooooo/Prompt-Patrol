import re

import spacy

MODEL = "en_core_web_sm"
_BREAKS = re.compile(r"(?:<br\s*/?>|\n)+")
# Endings that cannot close a sentence (comma, colon, open bracket,
# conjunction, article, possessive) mark the following line break as a
# wrap rather than a boundary
_CONTINUATION = re.compile(r"([,;:(]|\b(and|or|but|a|an|the|its|their))\s*$", re.IGNORECASE)
_LEADING_CONTINUATION = re.compile(r"^(and|or|but|nor)\b")
_nlp = None


def _pipeline():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(MODEL, exclude=["ner", "lemmatizer"])
    return _nlp


def segment(text: str) -> list[str]:
    """Split an answer into sentences.

    Line breaks count as sentence boundaries. The validation set showed
    students ending sentences with breaks instead of full stops far more
    often than wrapping one sentence across lines. A break is treated as
    a wrap when the previous chunk cannot grammatically end a sentence,
    or when the next chunk starts with a lowercase coordinating
    conjunction. Wraps with no grammatical signal still split, which the
    validation in docs/segmentation_review_v1.md to v3 measures.
    """
    chunks = []
    for raw in _BREAKS.split(text):
        raw = raw.strip()
        if not raw:
            continue
        joins_back = chunks and _CONTINUATION.search(chunks[-1])
        joins_forward = chunks and raw[0].islower() and _LEADING_CONTINUATION.match(raw)
        if joins_back or joins_forward:
            chunks[-1] = chunks[-1] + " " + raw
        else:
            chunks.append(raw)

    sentences = []
    for chunk in chunks:
        doc = _pipeline()(chunk)
        sentences.extend(s.text.strip() for s in doc.sents if s.text.strip())
    return sentences
