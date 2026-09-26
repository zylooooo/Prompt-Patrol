"""Prompt templates for the paraphrase pass.

Versioned like the harness templates: a template is never edited after
paraphrases exist that used it, a change gets a new version.
"""

SYSTEM = (
    "You rewrite short answers written by university students. Reply with "
    "the rewritten answer only, with no preamble, no quotes and no notes."
)

TEMPLATES = {
    "light_v1": (
        "Lightly paraphrase this answer. Swap some words for synonyms and "
        "make small changes to word order, but keep every sentence. Keep the "
        "meaning, the level of detail, the rough length and any mistakes "
        "exactly as they are.\n\nAnswer: {answer}"
    ),
    "heavy_v1": (
        "Heavily paraphrase this answer. Restructure every sentence and "
        "reword it completely. Keep the meaning, the level of detail, the "
        "rough length and any mistakes exactly as they are.\n\nAnswer: {answer}"
    ),
    # v2 after the pilot spot-check: v1 swapped key technical terms for
    # near-synonyms ("named" to "designated"), which changes the answer, and
    # heavy rewrites drifted into a formal register no student writes in
    "light_v2": (
        "Lightly paraphrase this answer. Swap some everyday words for "
        "synonyms and make small changes to word order, but keep every "
        "sentence. Keep every technical term and key word exactly as "
        "written. Keep the meaning, the level of detail, the rough length, "
        "the casual student tone and any mistakes exactly as they are.\n\n"
        "Answer: {answer}"
    ),
    "heavy_v2": (
        "Heavily paraphrase this answer. Restructure every sentence and "
        "reword it in your own way, the way a student would write it in "
        "their own words. Keep every technical term and key word exactly as "
        "written. Keep the meaning, the level of detail, the rough length, "
        "the casual student tone and any mistakes exactly as they are. Do "
        "not make it sound more formal.\n\nAnswer: {answer}"
    ),
}

STRENGTH_TO_TEMPLATE = {
    "light": "light_v2",
    "heavy": "heavy_v2",
}
