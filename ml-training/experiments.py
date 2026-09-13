"""
Every experiment config, in one place.

Adding an experiment means adding a RunConfig here; sweeping one means calling
.variant() in a loop. Defaults live in config.py, so an entry states only what
it changes - and a variant states only what differs from its parent, which is
what keeps a comparison attributable.

    from experiments import ROBERTA_DORA
    run(ROBERTA_DORA)
"""

from config import DataConfig, ModelConfig, OptimConfig, PeftConfig, RunConfig

OWNER = "tori.2023"
SPLITS = "data/splits/v0.1"

# revision is pinned to a commit sha, not "main". "main" is a moving branch
# pointer: if the checkpoint or tokenizer files are re-uploaded it silently
# changes underneath us, and fingerprint() cannot see it because the config
# string did not change. Pinning here covers every roberta run at once - a
# LoRA-vs-DoRA delta measured across two different base checkpoints is not a
# delta. Re-derive with HfApi().model_info(...).sha
ROBERTA = dict(
    family="roberta",
    base_model="FacebookAI/roberta-base",
    revision="e2da8e2f811d1448a5b465c236feacd80ffbac7b",   # 2024-02-19
)


# --------------------------------------------------------------------------
# E2 - the main comparison. Fine-tuned and zero-shot detectors, one table.
# --------------------------------------------------------------------------

ROBERTA_FULL = RunConfig(
    experiment="E2-finetune",
    run_name="roberta-base-full-ft",
    owner=OWNER,
    model=ModelConfig(**ROBERTA, tuning_method="full_ft"),
    data=DataConfig(splits=SPLITS),
    # the upper-capacity reference LoRA and DoRA are judged against. It also
    # shows how badly a full fine-tune overfits a corpus this small.
    optim=OptimConfig(learning_rate=2e-5),
)

ROBERTA_LORA = RunConfig(
    experiment="E2-finetune",
    run_name="roberta-base-lora-r16",
    owner=OWNER,
    model=ModelConfig(**ROBERTA, tuning_method="lora"),
    data=DataConfig(splits=SPLITS),
    peft=PeftConfig(r=16, alpha=32),
    # only the adapter moves, so a higher LR than full FT is expected.
    # Comparing LoRA at 2e-5 against full FT would be a rigged comparison.
    optim=OptimConfig(learning_rate=1e-4),
)

# DoRA differs from LoRA in exactly one field. Writing it as a variant makes
# that structural instead of a promise in a comment.
ROBERTA_DORA = ROBERTA_LORA.variant(
    "roberta-base-dora-r16", **{"model.tuning_method": "dora"}
)

BINOCULARS = RunConfig(
    experiment="E2-finetune",          # NOT a separate experiment - splitting
    run_name="binoculars-zeroshot",    # baselines out loses the headline table
    owner=OWNER,
    run_role="eval",                   # no training, but the same evaluate()
    model=ModelConfig(
        family="binoculars", base_model="tiiuae/falcon-7b", tuning_method="zeroshot",
        revision="ec89142b67d748a1865ea4451372db8313ada0d8",   # 2024-10-12
    ),
    data=DataConfig(splits=SPLITS),
)


# --------------------------------------------------------------------------
# E3 - reliability. One run per held-out generator; report the WORST.
# --------------------------------------------------------------------------

def logo(generator: str, slug: str) -> RunConfig:
    """Leave-one-generator-out: can the detector catch a model it never saw?"""
    return ROBERTA_LORA.variant(
        f"roberta-lora-logo-holdout-{slug}",
        experiment="E3-reliability",
        run_role="eval",
        **{
            "data.split_strategy": "logo",
            "data.held_out_generator": generator,
            "data.splits": f"data/splits/v0.1-logo-{slug}",
        },
    )


# --------------------------------------------------------------------------
# Smoke - pipeline shakedown on the 85-question trial file.
# Never cited: 85 questions x 4 answers, of which exactly one per question is
# AI, so 85 distinct AI texts total. A score here measures that corpus, not
# the detector. It exists to prove the run reaches DagsHub with predictions,
# thresholds and slices attached.
# --------------------------------------------------------------------------

TRIAL = ROBERTA_LORA.variant(
    "roberta-lora-r16-trial340",
    experiment="trial-run",
    run_role="smoke",
    notes=(
        "Smoke test on data/splits/trial-v0.2.parquet (85 questions x 4 answers, "
        "25% AI, group-split by question 60/20/20). NOT A RESULT - two known "
        "label leaks. (1) 21 human answers carry unstripped <br> markup from the "
        "Mohler source and no AI answer does, so `<br>` alone identifies a human "
        "with certainty; to be fixed in cleaned_data.ipynb before any cited run. "
        "(2) 98.8% of AI answers end in a full stop against 65.5% of human ones, "
        "and 92.9% start capitalised against 66.3%. That one is genuine signal, "
        "not an artefact, but it is shallow enough that a high AUROC here "
        "demonstrates punctuation matching, not detection. The corpus also has "
        "no per-model generator tag - `generator` is only human/ai_generated - "
        "so E3 leave-one-generator-out cannot run on it."
    ),
    **{
        "data.splits": "data/splits/trial-v0.2.parquet",

        # longest answer in the corpus is 86 words (median 13), so 256 tokens
        # is ~3x more padding than signal. Halving it halves the MPS step time
        # without truncating anything.
        "model.max_length": 128,
        "optim.epochs": 10,

        # no bf16 on Apple MPS
        "optim.precision": "fp32",

        # The project default selects on tpr_at_fpr_0.01. Val here has 51
        # negatives, so a 1% FPR budget permits 0.51 false positives - i.e.
        # zero - and TPR at that point moves in jumps of 1/17. That is a coin
        # flip as a model-selection signal, so the smoke run selects on AUROC.
        # The headline metric is still reported; it is just not steering
        # checkpoint choice on 68 validation rows.
        "optim.metric_for_best_model": "auroc",

        # 25% AI, a 3:1 ratio. Reweighting would distort the probabilities the
        # Platt calibrator is then fitted on, for a skew this mild.
        "optim.class_weight": "none",
    },
)
