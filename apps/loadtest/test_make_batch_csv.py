"""Tests for make_batch_csv."""

import csv
import json
import os
import tempfile
import unittest

from make_batch_csv import load_rows, main, sample_rows


def _write_corpus(path: str, answers: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["", "question", "answer", "generator"])
        for i, a in enumerate(answers):
            w.writerow([i, f"q{i}", a, "human"])


class MakeBatchCsvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src.csv")

    def test_filters_short_and_empty_answers(self) -> None:
        _write_corpus(self.src, ["", "short", "x" * 10, "y" * 10001, "  short   ", "  " + "z" * 10 + "  "])
        rows = load_rows(self.src)
        self.assertEqual([r["answer_text"] for r in rows], ["x" * 10, "z" * 10])

    def test_drops_overlong_question(self) -> None:
        with open(self.src, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["", "question", "answer", "generator"])
            w.writerow([0, "q" * 2001, "a" * 20, "human"])
            w.writerow([1, "q" * 2000, "b" * 20, "human"])
        self.assertEqual([r["answer_text"] for r in load_rows(self.src)], ["b" * 20])

    def test_sample_is_deterministic_and_sized(self) -> None:
        rows = [{"answer_text": "a" * 10 + str(i), "question_text": "q"} for i in range(5)]
        self.assertEqual(sample_rows(rows, 500, 7), sample_rows(rows, 500, 7))
        self.assertEqual(len(sample_rows(rows, 500, 7)), 500)
        self.assertEqual(len(sample_rows(rows, 3, 7)), 3)

    def test_cli_writes_batch_and_answers(self) -> None:
        _write_corpus(self.src, [f'ans, "quoted" number {i:03d}' for i in range(30)])
        out = os.path.join(self.tmp.name, "out")
        main(["--rows", "20", "--seed", "1", "--out-dir", out, "--source", self.src])
        with open(os.path.join(out, "batch.csv"), newline="", encoding="utf-8") as f:
            lines = f.read().splitlines()
            f.seek(0)
            data = list(csv.DictReader(f))
        self.assertEqual(lines[0], "external_ref,answer_text,question_text")
        self.assertEqual(len(data), 20)
        self.assertEqual(data[0]["external_ref"], "lt-0001")
        with open(os.path.join(out, "answers.json"), encoding="utf-8") as f:
            answers = json.load(f)
        self.assertEqual(len(answers), 30)
        self.assertTrue(all(set(a) == {"answer_text", "question_text"} for a in answers))


if __name__ == "__main__":
    unittest.main()
