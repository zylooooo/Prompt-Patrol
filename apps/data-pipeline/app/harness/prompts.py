"""Prompt templates for the generation harness.

Template names are versioned (weak_v1). A template is never edited after
answers exist that were generated with it. A change gets a new version,
so the prompt_template field in every record stays accurate.
"""

SYSTEM = (
    "You are a university student answering a short-answer question in an "
    "undergraduate computer science course. Write the way students write "
    "under time pressure, in plain sentences with no lists, no headings and "
    "no introductions. Reply with the answer text only. Keep it as short as "
    "the question deserves. A single phrase is fine if that is all it needs."
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
    # variant that shows the reference answer, compare against wrong_v1
    # in the pilot
    "wrong_ref_v1": (
        "Here is a question and its correct answer. Write a plausible "
        "INCORRECT answer that a confidently mistaken student might give "
        "instead. Do not reuse the correct answer's wording.\n\n"
        "Question: {question}\nCorrect answer: {instructor_answer}"
    ),
}

TIER_TO_TEMPLATE = {
    "correct": "correct_v1",
    "weak": "weak_v1",
    "partial": "partial_v1",
    "wrong": "wrong_v1",
}
