import pytest

pytest.importorskip("en_core_web_sm")  # skip when the spacy model is not installed

from splicer.segment import segment


def test_technical_tokens_do_not_split_sentences():
    sentences = segment("A hash table gives O(1) lookup. A list does not.")
    assert len(sentences) == 2
    assert "O(1)" in sentences[0]


def test_decimal_does_not_split():
    assert len(segment("The load factor is 0.75 in Java. It can be changed.")) == 2


def test_single_sentence_stays_whole():
    assert segment("Push adds an element to the top of the stack.") == [
        "Push adds an element to the top of the stack."
    ]


def test_break_tag_is_a_hard_boundary():
    sentences = segment("There is no base case.<br>The step does not reduce the problem.")
    assert len(sentences) == 2
    assert "<br" not in " ".join(sentences)


def test_unpunctuated_break_still_splits():
    sentences = segment("global variables are declared in main<br>local variables anywhere else")
    assert len(sentences) == 2


def test_break_after_conjunction_is_a_wrap_not_a_boundary():
    sentences = segment("push, which adds an item, and<br>pop, which removes one")
    assert len(sentences) == 1


def test_lowercase_leading_conjunction_joins():
    assert len(segment("no base case<br>or if the base case is never reached")) == 1
    