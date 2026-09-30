"""Prompt templates for the generation harness.

Template names are versioned (weak_v3). A template is never edited after
answers exist that were generated with it, and neither is the system
prompt it is sent with (SYSTEM or its SYSTEM_OVERRIDES entry). A change
to either gets a new template version, so the prompt_template field in
every record stays accurate. The course strings in harness/configs fill
SYSTEM, so quality-tier records store their course too, and a resume
refuses answers made with another template or course. Retired versions
were only ever used in smoke runs and are not kept.
"""

# {course} comes from the dataset config, without it models answer a
# Python course's questions about Java and C. Without the tone and
# self-remark rules, weak, partial and wrong answers turn casual and talk
# about what the writer does not remember
SYSTEM = (
    "You are a university student answering a short-answer exam question in "
    "{course}. Write the way students write under time pressure, in plain "
    "text with no lists, headings, markdown or preambles such as Sure or Here "
    "is my answer. Keep the neutral tone of a written exam answer, with no "
    "casual filler such as like, basically or just. Do not bring the course "
    "name into the answer, and never comment on how sure you are or on what "
    "you remember or left out. Reply with the answer text only."
)

# editor instruction from Tufts, Zhao and Li (Table 13), sent as the system
# prompt in place of the student persona, which it would contradict
REWRITE_SYSTEM = (
    "You are a helpful writing assistant. Rewrite the following text to "
    "improve clarity and professionalism. Do not provide any other text. "
    "Only provide the rewritten text."
)

# {target_words} is the length of a real student answer to the same
# question, see generate.pick_target_words
TEMPLATES = {
    "correct_v3": (
        "Answer the question correctly in about {target_words} words."
        "\n\nQuestion: {question}"
    ),
    # the weakness has to sit in the content, otherwise models show it
    # through casual wording and still answer correctly
    "weak_v3": (
        "Answer as a student who only half remembers this topic: use the "
        "subject's own technical terms, but loosely or incompletely, with a gap "
        "or a slightly misused concept in the reasoning. It should not be "
        "completely wrong. The weakness is in what you say, not in how casually "
        "you say it, so do not swap technical terms for everyday words. "
        "Use about {target_words} words.\n\nQuestion: {question}"
    ),
    "partial_v3": (
        "Answer as a student who understands part of this and misses the rest: "
        "get one aspect right and get the rest wrong or leave it out. Write only "
        "what you believe and stop there, without saying that anything is "
        "missing or that you are unsure. Use about {target_words} words."
        "\n\nQuestion: {question}"
    ),
    # without these limits models fall back on stock reversals and can
    # flip their own verdict
    "wrong_v3": (
        "Answer as a student who is confidently mistaken: give a plausible but "
        "incorrect answer built on a misunderstanding a student who studied "
        "this could really have, such as getting the mechanism or a rule wrong, "
        "or mixing it up with a related idea. Do not simply state the opposite "
        "of the correct answer, do not argue from the words in the term's name, "
        "and do not include the correct idea anywhere. If the question asks for "
        "TRUE or FALSE, give the incorrect verdict and never correct yourself. "
        "Do not hint that it is wrong. Use about {target_words} words."
        "\n\nQuestion: {question}"
    ),
    # only the student answer goes in, REWRITE_SYSTEM carries the instruction
    "rewrite_human_v1": "{student_answer}",
}

# system prompts that replace the student persona, keyed by template
SYSTEM_OVERRIDES = {"rewrite_human_v1": REWRITE_SYSTEM}

TIER_TO_TEMPLATE = {
    "correct": "correct_v3",
    "weak": "weak_v3",
    "partial": "partial_v3",
    "wrong": "wrong_v3",
    "rewrite": "rewrite_human_v1",
}

# tiers that send a real student answer to the model to polish
REWRITE_TIERS = {tier for tier, name in TIER_TO_TEMPLATE.items() if "{student_answer}" in TEMPLATES[name]}


def is_rewrite(record):
    """True for a rewrite, or anything made from one, since paraphrase and
    human-edit records keep their source's tier. The splicer, paraphrase
    and human-edit passes all skip these, so they only take answers the
    model wrote itself."""
    return record.get("tier") in REWRITE_TIERS
