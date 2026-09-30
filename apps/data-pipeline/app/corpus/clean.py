"""Surface cleanup applied to every answer, human and ai alike.

Formatting that only one side uses gives the label away without the
model learning anything about the writing. Students' answers carry line
breaks, <br> tags, HTML entities, list markers, answer-sheet labels and
LaTeX arrows, models write curly quotes, long dashes and backticks. The
detector has to apply the same cleanup to submitted text, or what it
scores will not look like what it trained on.
"""

import html
import re
from html.entities import html5

CLEANING_VERSION = "clean_v2"

# numeric references and complete named entities only, html.unescape on
# its own also decodes legacy names without a semicolon, so C++ &param
# would turn into a pilcrow
_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_BR = re.compile(r"<br\s*/?>|\r\n?", re.IGNORECASE)
# answer-sheet labels such as "A:" or "Ans)", stacked ones too, the \b
# keeps "Answer" whole
_LABEL = re.compile(r"^\s*(?:(?:A\s*[:)]|Ans\b\s*[:).]?)\s*)+", re.IGNORECASE)
# only markers that touch no word, so **kwargs and x**2 survive
_BOLD = re.compile(r"(?<![\w*])\*\*(?=[^\s*])([^*]+?)(?<=\S)\*\*(?![\w*])")
# a verdict alone on its first line would run into the next sentence
_VERDICT = re.compile(r"^\s*(true|false)[ \t]*\n", re.IGNORECASE)
# bullets, numbers and letters opening a line, stacked or not. The space
# after them keeps *args whole, and T. or F. verdicts are left alone
_LIST_MARKER = re.compile(
    r"^[ \t]*(?:(?:[-*\N{BULLET}]|\(?\d{1,2}[.)]|\(?[a-zA-Z]\)|[a-z]\.)[ \t]+)+", re.MULTILINE,
)
# a line that ends without punctuation before a capital was a sentence
# end, joined with a bare space it would read as a run-on only students write
_SENTENCE_BREAK = re.compile(r"(?<=[A-Za-z0-9])[ \t]*\n\s*(?=[A-Z])")
_ARROW = re.compile(r"\$?\\[Rr]ightarrow\$?")
# fork() and fork name the same call, students write the brackets far more
_EMPTY_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(\s*\)")
_CHARACTERS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
    "`": None,
})


def _decode(match):
    entity = match.group(0)
    return html.unescape(entity) if entity[1] == "#" or entity[1:] in html5 else entity


def clean_text(text):
    """HTML entities are decoded and every break becomes a newline, so the
    line rules see the same shape in each dataset. Then **bold** markers,
    list markers and answer labels go, a lone first-line verdict and
    any unpunctuated line before a capital get a full stop, LaTeX arrows
    become ->, empty call brackets go, curly quotes and long dashes
    become plain ones, backticks go, and all whitespace, newlines
    included, collapses to single spaces."""
    text = _BR.sub("\n", _ENTITY.sub(_decode, str(text)))
    # labels, numbers and bold can hide behind one another ("1. Ans: a) x"),
    # so strip them until nothing changes, which keeps the result stable
    while True:
        stripped = _LABEL.sub("", _LIST_MARKER.sub("", _BOLD.sub(r"\1", text)))
        if stripped == text:
            break
        text = stripped
    text = _SENTENCE_BREAK.sub(". ", _VERDICT.sub(r"\1. ", text))
    text = _EMPTY_CALL.sub(r"\1", _ARROW.sub(" -> ", text))
    return " ".join(text.translate(_CHARACTERS).split())
