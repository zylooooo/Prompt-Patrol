import pytest

from corpus.clean import clean_text


@pytest.mark.parametrize("raw, cleaned", [
    ("first line<br>second<BR/>third<br />fourth", "first line second third fourth"),
    ("one\ntwo\r\nthree", "one two three"),
    ("it\u2019s the \u201cstack\u201d", 'it\'s the "stack"'),
    ("push\u2014then pop \u2013 done", "push-then pop - done"),
    ("and so on\u2026", "and so on..."),
    ("use `*args` here", "use *args here"),
    ("the answer is **false** because", "the answer is false because"),
    ("  lots   of\t space\u00a0here  ", "lots of space here"),
    ("a &amp; b &lt;iostream&gt;", "a & b <iostream>"),
    ("A: the parent", "the parent"),
    ("Ans) it blocks", "it blocks"),
    ("Answer: yes", "Answer: yes"),
    ("False\nThe parent can", "False. The parent can"),
    ("**False**<br>The parent can", "False. The parent can"),
    ("False, because", "False, because"),
    ("- push\n- pop", "push pop"),
    ("1. push<br>2) pop", "push pop"),
    ("3.5 is a float", "3.5 is a float"),
    ("a $\\rightarrow$ b", "a -> b"),
    ("fork() then exec( )", "fork then exec"),
    ("range(0, 2) stays", "range(0, 2) stays"),
    ("def f(**kwargs): return g(**kwargs)", "def f(**kwargs): return g(**kwargs)"),
    ("x**2 + y**2", "x**2 + y**2"),
    ("2**10 is 1024 and 2**3 is 8", "2**10 is 1024 and 2**3 is 8"),
    ("d = {**a, **b}", "d = {**a, **b}"),
    ("**TRUE** because", "TRUE because"),
    ("(**TRUE**)", "(TRUE)"),
    ("int &param", "int &param"),
    ("p = &param;", "p = &param;"),
    ("1. fork creates\n2. Exec replaces", "fork creates. Exec replaces"),
    ("(a) first\n(b) second", "first second"),
    ("T\nThe parent", "T. The parent"),
    ("1. Ans: a) the parent", "the parent"),
    ("1)Word one", "Word one"),
    ("1.Word one", "Word one"),
    ("(ii) second", "second"),
    ("-> x", "x"),
    ("Solution: use a lock", "use a lock"),
    ("Solution is to lock", "Solution is to lock"),
    ("10 - 3 = 7", "10 - 3 = 7"),
    ("tuple uses () and list uses []", "tuple uses () and list uses []"),
    ("defined with ( )", "defined with ( )"),
    ("p = &num;", "p = &num;"),
    ("p = &sum;", "p = &sum;"),
    ("gives the\nCPU", "gives the CPU"),
    ("call fork()\nThe child", "call fork. The child"),
    ("False\nthe parent can", "False. the parent can"),
    ("true\nbecause it", "true. because it"),
    ("It ends here.\nNext", "It ends here. Next"),
    ("size 10\nThe next", "size 10. The next"),
    ("first  \nSecond", "first. Second"),
    ("fork () returns", "fork returns"),
    ("(1) x", "x"),
    ("a. x", "x"),
    ("&#39;", "'"),
    ("&#x27;", "'"),
    ("fork\r\nThe child", "fork. The child"),
    ("Ans. x", "x"),
    ("\N{BULLET} x", "x"),
    ("a $\\Rightarrow$ b", "a -> b"),
    ("$\\rightarrow$ x at the start of a line", "x at the start of a line"),
    ("x**b**", "x**b**"),
    ("_init() runs", "_init runs"),
    ("a$\\rightarrow$b", "a -> b"),
    ("False \nthe", "False. the"),
    ("1. A: 2. A: 3. x", "x"),
])
def test_each_rule(raw, cleaned):
    assert clean_text(raw) == cleaned


def test_python_stars_survive_even_at_the_start_of_a_line():
    assert clean_text("def f(*args, **kwargs):") == "def f(*args, **kwargs):"
    assert clean_text("*args collects the rest") == "*args collects the rest"


def test_an_escaped_break_tag_becomes_a_space():
    assert clean_text("one&lt;br&gt;two") == "one two"


@pytest.mark.parametrize("text", [
    "it\u2019s <br> `x` \u2014 **bold**\nend",
    "1. Ans: a) **b)** the parent<br>2. The child",
    "A: A: - * 1) x",
    "1.\nfork creates a child",
    "-\npush",
    "\N{EN DASH} push\n\N{EN DASH} pop",
    "`A:` the parent",
    "1. push",
])
def test_cleaning_twice_changes_nothing(text):
    assert clean_text(clean_text(text)) == clean_text(text)
