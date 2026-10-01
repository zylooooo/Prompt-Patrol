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

CLEANING_VERSION = "clean_v2"

# numeric references and the named escapes the corpora use, other names
# stay as written, so C and C++ address-of code such as &param or &sum
# is never decoded into a symbol
_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|amp|lt|gt|quot|apos|nbsp);")
_BR = re.compile(r"<br\s*/?>|\r\n?", re.IGNORECASE)
# answer-sheet labels such as "A:", "Ans)" or "Solution:", stacked ones
# too, the \b keeps "Answer" whole and "Solution" needs its colon
_LABEL = re.compile(r"^\s*(?:(?:A\s*[:)]|Ans\b\s*[:).]?|Sol(?:ution)?\s*:)\s*)+", re.IGNORECASE)
# only markers that touch no word, so **kwargs and x**2 survive
_BOLD = re.compile(r"(?<![\w*])\*\*(?=[^\s*])([^*]+?)(?<=\S)\*\*(?![\w*])")
# a verdict alone on its first line would run into the next sentence
_VERDICT = re.compile(r"^\s*(true|false)[ \t]*\n", re.IGNORECASE)
# bullets, numbers, letters, roman numerals and arrows opening a line,
# stacked or not. A space or line end after the plain markers keeps *args
# whole, and T. or F. verdicts are left alone
_LIST_MARKER = re.compile(
    r"^[ \t]*(?:"
    r"(?:[-*\N{BULLET}]|\(?\d{1,2}[.)]|\(?[a-zA-Z]\)|[a-z]\.)(?:[ \t]+|$)"
    r"|\(?\d{1,2}\)(?=\S)|\d{1,2}\.(?=[A-Z])"
    r"|\(?(?:ii|iii|iv|vi|vii|viii|ix)[.)][ \t]*"
    r"|(?:->|=>)[ \t]+|\d{1,2}[-:][ \t]+|-(?=[A-Z][a-z])"
    r")+",
    re.MULTILINE,
)
# a line that ends without punctuation before a capital was a sentence
# end, joined with a bare space it would read as a run-on only students
# write. Not after a function word, where the line only wrapped ("the\nCPU")
_SENTENCE_BREAK = re.compile(
    r"(?<=[A-Za-z0-9])(?<!\bthe)(?<!\ba)(?<!\ban)(?<!\bof)(?<!\bto)(?<!\bin)(?<!\band)(?<!\bor)(?<!\bif)"
    r"(?<!\bthat)(?<!\bfor)(?<!\busing)(?<!\bis)(?<!\bare)(?<!\bwhich)(?<!\bby)(?<!\bwith)(?<!\bfrom)"
    r"[ \t]*\n\s*(?=[A-Z])"
)
_ARROW = re.compile(r"\$?\\[Rr]ightarrow\$?")
# fork() and fork name the same call, students write the brackets far more.
# Brackets named as a symbol ("a tuple uses ()") stay
_EMPTY_CALL = re.compile(
    r"\b(?!(?:and|as|by|in|is|of|or|the|use[sd]?|using|with|brackets?|parenthes[ie]s)\s)([A-Za-z_]\w*)\s*\(\s*\)"
)
_CHARACTERS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
    "`": None,
})


def clean_text(text):
    """HTML escapes are decoded and every break becomes a newline, so the
    line rules see the same shape in each dataset. LaTeX arrows become
    ->, curly quotes and long dashes become plain ones and backticks go.
    Then **bold** markers, list markers and answer labels go, empty call
    brackets go, a lone first-line verdict and any unpunctuated line
    before a capital get a full stop, and all whitespace, newlines
    included, collapses to single spaces."""
    text = _BR.sub("\n", _ENTITY.sub(lambda match: html.unescape(match.group(0)), str(text)))
    # characters first, so a dash or backtick cannot hide a marker from the loop
    text = _ARROW.sub(" -> ", text).translate(_CHARACTERS)
    # labels, numbers and bold can hide behind one another ("1. Ans: a) x"),
    # so strip them until nothing changes
    while True:
        stripped = _LABEL.sub("", _LIST_MARKER.sub("", _BOLD.sub(r"\1", text)))
        if stripped == text:
            break
        text = stripped
    # brackets go first, so "call fork()" before a new line still gets its full stop
    text = _EMPTY_CALL.sub(r"\1", text)
    text = _SENTENCE_BREAK.sub(". ", _VERDICT.sub(r"\1. ", text))
    return " ".join(text.split())
