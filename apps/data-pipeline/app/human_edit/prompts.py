"""Prompt for the simulated editing pass.

Versioned like the harness templates: a template is never edited after
records exist that used it, a change gets a new version. The examples and
edit-type mix inside the prompt come from the genuine edits, see
simulate.build_prompt_spec.
"""

SYSTEM = (
    "You are a university student touching up an answer an AI wrote for "
    "you, just before you submit it. Reply with the edited answer only, "
    "with no preamble, no quotes and no notes."
)

EDIT_TYPE_TEXT = {
    "reorder": "move a sentence or phrase to a different place",
    "delete": "cut a sentence or part of one",
    "reword": "change some words into your own",
    "fact_tweak": "change a small detail, like a term, a number or an example",
}

TEMPLATE_NAME = "simulate_v1"

TEMPLATE = (
    "These are real examples of how students edited AI answers before "
    "submitting them:\n\n{examples}\n\n"
    "Now edit the answer below the same way. Make these kinds of edits: "
    "{edit_types}. Make a few quick changes like a student would, not to "
    "improve the answer. Keep most of the original wording, do not add new "
    "sentences or ideas, and keep any mistakes unless a small detail change "
    "touches them.\n\nAnswer: {answer}"
)

EXAMPLE = "Original: {source}\nEdited: {edited}"
