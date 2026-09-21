"""Build the hand-check file for the segmenter.

Twenty-five answers are drawn at random and up to twenty-five more from
answers containing known segmentation hazards (abbreviations, decimals,
big-O notation, break tags) so the hard cases are actually exercised.
"""

import re
from pathlib import Path

import pandas as pd

from splicer.segment import segment

PIPELINE_DIR = Path(__file__).parent.parent.parent
# raw on purpose, the segmenter must hold up on text cleaning has not touched
CORPUS = PIPELINE_DIR / "data" / "raw" / "mohler_raw.parquet"
# drafts land in gitignored data/, the reviewed copy is committed to docs/
OUT = PIPELINE_DIR / "data" / "segmentation_review_v3.md"
SEED = 480
HAZARD = re.compile(r"e\.g|i\.e|etc\.|O\(|\d\.\d|<br")


def main():
    df = pd.read_parquet(CORPUS)
    hazardous = df[df["student_answer"].str.contains(HAZARD)]
    plain = df.drop(hazardous.index)
    sample = pd.concat([
        hazardous.sample(min(25, len(hazardous)), random_state=SEED),
        plain.sample(25, random_state=SEED),
    ])

    lines = [
        "# Segmenter validation, fifty answers",
        "",
        "For each answer: OK if every sentence boundary is right, otherwise WRONG plus a note.",
        "",
    ]
    for _, row in sample.iterrows():
        lines.append(f"## {row['id']}")
        lines.append("")
        for i, sentence in enumerate(segment(row["student_answer"]), 1):
            lines.append(f"{i}. {sentence}")
        lines.extend(["", "verdict: ", ""])
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} with {len(sample)} answers")


if __name__ == "__main__":
    main()
