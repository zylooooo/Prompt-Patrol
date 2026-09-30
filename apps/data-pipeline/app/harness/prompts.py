"""Prompt templates for the generation harness.

Template names are versioned (weak_v1). A template is never edited after
answers exist that were generated with it, and neither is the system
prompt it is sent with (SYSTEM or its SYSTEM_OVERRIDES entry). A change
to either gets a new template version, so the prompt_template field in
every record stays accurate.
"""

SYSTEM = (
    "You are a university student answering a short-answer question in an "
    "undergraduate computer science course. Write the way students write "
    "under time pressure, in plain sentences with no lists, no headings and "
    "no introductions. Reply with the answer text only. Keep it as short as "
    "the question deserves. A single phrase is fine if that is all it needs."
)

# editor instruction from Tufts, Zhao and Li (Table 13), sent as the system
# prompt in place of the student persona, which it would contradict
REWRITE_SYSTEM = (
    "You are a helpful writing assistant. Rewrite the following text to "
    "improve clarity and professionalism. Do not provide any other text. "
    "Only provide the rewritten text."
)

TEMPLATES = {
    "correct_v1": (
        "Answer the question correctly and concisely.\n\nQuestion: {question}"
    ),
    "weak_v1": (
        "Answer as a student who only half remembers this topic: vague "
        "wording, an imprecise term or two, some hedging, but not completely "
        "wrong.\n\nQuestion: {question}"
    ),
    "partial_v1": (
        "Answer as a student who understands part of this and misses the "
        "rest: get one aspect right and leave the answer incomplete or "
        "slightly confused.\n\nQuestion: {question}"
    ),
    "wrong_v1": (
        "Answer as a student who is confidently mistaken: give a plausible "
        "but incorrect answer built on a common misconception. Do not hint "
        "that it is wrong.\n\nQuestion: {question}"
    ),
    # only the student answer goes in, REWRITE_SYSTEM carries the instruction
    "rewrite_human_v1": "{student_answer}",
}

# system prompts that replace the student persona, keyed by template
SYSTEM_OVERRIDES = {"rewrite_human_v1": REWRITE_SYSTEM}

TIER_TO_TEMPLATE = {
    "correct": "correct_v1",
    "weak": "weak_v1",
    "partial": "partial_v1",
    "wrong": "wrong_v1",
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
