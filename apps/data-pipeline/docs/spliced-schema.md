# Spliced corpus record schema

One JSON object per line in data/spliced/spliced_<dataset>.jsonl. Example:

    {
      "doc_id": "spliced/mohler/f50/0007",
      "question_id": "mohler/E03.Q03",
      "human_answer_id": "mohler/E03.Q03.A05",
      "ai_answer_id": "mohler/E03.Q03/gpt-5.5/weak/01",
      "target_ai_fraction": 0.5,
      "ai_fraction": 0.5,
      "sentences": [
        {"text": "...", "label": "human"},
        {"text": "...", "label": "ai"}
      ]
    }

Field notes:
- Both source ids are recorded so every document traces to one human and
  one AI answer to the same question. Splits are inherited through
  question_id.
- ai_fraction is the realised fraction (replaced sentences over total)
  and can differ from target_ai_fraction on short answers. Evaluation
  reports by ai_fraction.
- sentences preserves document order. label is "human" or "ai", nothing
  else.
- Human base answers pass the eligibility rule in app/splicer/splice.py.
  The AI donor side has no eligibility rule, only splice_pair's
  sentence-count check and the rewrite skip below. Human exclusions and
  rewrite skips are logged at build time, pairs that splice_pair rejects
  are not counted.
- Rewrites are never spliced. The splicer skips every record that
  is_rewrite in app/harness/prompts.py flags, so each ai sentence comes
  from an answer the model wrote itself.
