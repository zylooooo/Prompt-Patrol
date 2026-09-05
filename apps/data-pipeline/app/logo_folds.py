import logging

import pandas as pd

from splitting import SPLITS_PATH

logger = logging.getLogger(__name__)

HUMAN_LABEL = "human"


def leave_one_generator_out(df: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    """One fold per AI generator, holding that generator's answers out entirely.

    Human answers keep whatever train/val/test `partition` 
    The held-out generator's rows go only to
    test; every other generator's rows go only to train. 
    """
    if "generator" not in df.columns:
        raise ValueError("No 'generator' column - LOGO needs AI-generated rows tagged by which model produced them.")

    ai_generators = sorted(g for g in df["generator"].unique() if g != HUMAN_LABEL)
    if not ai_generators:
        raise ValueError(f"No AI generators found (only {HUMAN_LABEL!r}) - nothing to leave out.")

    human_rows = df[df["generator"] == HUMAN_LABEL]
    human_train = human_rows[human_rows["partition"] == "train"]
    human_eval = human_rows[human_rows["partition"] != "train"]

    folds = {}
    for generator in ai_generators:
        held_out = df[df["generator"] == generator]
        other_ai = df[(df["generator"] != generator) & (df["generator"] != HUMAN_LABEL)]
        folds[generator] = {
            "train": pd.concat([human_train, other_ai], ignore_index=True),
            "test": pd.concat([human_eval, held_out], ignore_index=True),
        }
    return folds


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        df = pd.read_parquet(SPLITS_PATH)
    except FileNotFoundError:
        logger.error("No split file found at %s - run splitting.py first.", SPLITS_PATH)
        return

    if "generator" not in df.columns:
        logger.error(
            "This dataset has no 'generator' column - LOGO folds need AI-generated "
            "answers tagged by which model produced them. "
        )
        return

    folds = leave_one_generator_out(df)
    for generator, fold in folds.items():
        logger.info("Fold '%s' held out: train=%d rows, test=%d rows", generator, len(fold["train"]), len(fold["test"]))


if __name__ == "__main__":
    main()
