"""Build the load-test inputs (batch.csv, answers.json) from the trial corpus."""

import argparse
import csv
import json
import os
import random

MIN_LEN, MAX_LEN = 10, 10000
QUESTION_MAX = 2000  # mirrors QUESTION_MAX_CHARS in apps/api batches_service


def load_rows(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            answer = (r.get("answer") or "").strip()
            question = (r.get("question") or "").strip()
            if MIN_LEN <= len(answer) <= MAX_LEN and len(question) <= QUESTION_MAX:
                rows.append({"answer_text": answer, "question_text": question})
    return rows


def sample_rows(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return rng.choices(rows, k=n) if n > len(rows) else rng.sample(rows, n)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--source", default="/repo/docs/assets/trial-data.csv")
    args = p.parse_args(argv)

    rows = load_rows(args.source)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "batch.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["external_ref", "answer_text", "question_text"])
        for i, r in enumerate(sample_rows(rows, args.rows, args.seed), 1):
            w.writerow([f"lt-{i:04d}", r["answer_text"], r["question_text"]])
    with open(os.path.join(args.out_dir, "answers.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
