# Spliced answers schema

`app/splicer/build_spliced.py` writes `data/corpus/<version>-spliced.parquet`
and `<version>-spliced_manifest.json` next to the corpus version it reads.
One row per spliced answer: a student answer with some of its sentences
replaced, in place, by the first sentences of an AI answer to the same
question.

| Column | Type | Content |
|---|---|---|
| answer | string | the spliced text |
| label | int | 1 |
| partition | string | the partition of the question |
| question_id | string | the question |
| answer_id | string | `spliced/<partition>/<dataset>/b<band>/<nnnn>` |
| generator | string | the model that wrote the AI sentences |
| n_words | int | words, by `count_words` |
| dataset | string | mohler, sprag or engsaf |
| tier | string | the tier of the AI answer |
| style | string | spliced-25, spliced-50 or spliced-75 |
| ai_fraction | float | share of the words that are AI, 4 decimals |
| human_answer_id | string | the student answer spliced into |
| ai_answer_id | string | the AI answer the sentences came from |
| n_sentences | int | sentences in the spliced answer |
| ai_positions | list of int | positions of the AI sentences, zero-based |

Field notes:
- The first seven columns follow the load_splits() column contract. The
  file holds only the configured partitions, test by default, so
  ml-training scores it as an extra test-only file rather than loading it
  with load_splits(), which expects train, val and test.
- label is always 1. The file measures how often a detector flags
  answers that are partly AI, band by band. The false-positive rate still
  comes from the student answers in the corpus version.
- ai_fraction counts words with `count_words`, the corpus word rule.
  style names the band it falls in: spliced-25 (0.15 to 0.35), spliced-50
  (0.40 to 0.60) or spliced-75 (0.65 to 0.85).
- Each configured partition is spliced only from its own rows, test by
  default, so no sentence the detector trained on reaches a spliced
  answer.
- A student answer is a base only if it passes `is_eligible` in
  `app/splicer/splice.py`: at least `min_sentences` sentences (2 by
  default), prose, no code fragments, few ellipses and mostly
  full-length sentences. AI answers come from the corpus version, so
  its wrong-tier trim applies and rewrite-tier answers never appear.
- answer is the sentences joined with single spaces, and `clean_text`
  leaves it unchanged, so spliced answers look like corpus answers.

## Reporting

The rows are not independent. Spliced answers built from the same
question, student answer or AI answer tend to be caught or missed
together, so the rows carry much less evidence than the same number of
unrelated answers. In the v0.1 build, per band:

| Dataset | Questions | Effective questions | Fewest AI answers behind one model |
|---|---|---|---|
| Mohler | 14 | 10.7 to 12.6 | 9 |
| SPRAG | 7 to 8 | 2.7 to 4.2 | 5 |
| EngSAF | 2 | 1.0 to 1.2 | 2 |
| Pooled | 23 to 24 | 6.8 to 7.0 | 19 |

Effective questions is what the plain rate over the rows is worth,
counted in equally sized questions, if answers to one question are
caught or missed together. It is the squared sum of the answers per
question over the sum of their squares. The clustering comes from four
places:

- EngSAF's test partition has two questions, and `engsaf/Q2` holds 196
  of its 239 test student answers and 129 of the 135 that can serve as
  a base, so 256 of the 270 EngSAF spliced answers come from it. The
  main v0.1 test has the same limit for EngSAF.
- `sprag/PythonQ027` gives 141 of the 270 SPRAG spliced answers. It
  has 84 of the 332 SPRAG test student answers, more than any other
  question, and 42 of the 73 that can serve as a base.
- AI answers are reused. One EngSAF AI answer appears in 25 spliced
  answers across the bands, and in EngSAF band 25 two models each draw
  their 15 answers from 2 AI answers.
- Each dataset gets the same count per band, so when the datasets are
  pooled, `engsaf/Q2` weighs almost as much as all 14 Mohler questions.
  It and `sprag/PythonQ027` supply about half of every pooled band.

To report the detection rate:

- Compute it per question first and average across questions, so each
  question counts once. Give the plain rate over all rows beside it.
  The two can differ because the largest questions are caught at a
  different rate from the rest, because a question with one or two
  answers in a band has an extreme rate, or, when pooled, because they
  weight the datasets differently. Check which before reading the gap.
- Build intervals by resampling questions, not rows. A binomial
  interval over the rows is far too narrow. Resampling questions also
  covers reused student and AI answers, since both stay within one
  question. With few questions the interval still runs narrow, so treat
  SPRAG's as rough.
- Mohler per band is the best-supported per-dataset result. Report
  SPRAG with a note that one question supplies half of it. Report
  EngSAF as a single-question case, the rate over the `engsaf/Q2` rows
  alone, leaving out the 2 to 7 `engsaf/Q16` answers per band. In each
  band its 83 to 88 rows come from 60 or 61 student answers and 17 to
  21 AI answers, so build its interval per band with a two-way
  bootstrap. Draw the student answers and the
  AI answers independently with replacement, and weight each row by how
  often its student answer was drawn times how often its AI answer was
  drawn. Resampling the rows instead gives too narrow an interval.
- Per-model rates within one dataset and band rest on 2 to 14 AI
  answers. Pool each model across datasets, where it has at least 19 AI
  answers per band, and give its plain rate over its 45 answers. A
  per-question average does not suit models, since each covers only 11
  to 18 of the 23 or 24 questions in a band and many of those hold one
  or two of its answers. Only 2 to 4 questions per band have answers
  from all six models, and 11 to 15 of each model's 45 come from
  `engsaf/Q2`, so a gap between two models can come from the questions
  each drew. Resample by question and read per-model differences as
  rough.
- Bands within a dataset share most questions, and 178 of the 296
  student answers appear in more than one band, so compare bands on the
  per-question rate, using the same resampled questions for every band.
  Question shares still shift between bands (`sprag/PythonQ027` gives
  39, 49 and 53 of the 90 SPRAG answers in bands 25, 50 and 75, and
  `sprag/PythonQ061` is absent from band 75, so leave it out of any
  comparison with band 75). Higher bands are also
  built from shorter student answers, since a small AI share needs a
  long base (Mohler bases average 42 words in band 25 and 28 in band
  75), so a trend across bands mixes AI share with answer length.

## Manifest

`<version>-spliced_manifest.json` records the version, built_at, the
source corpus path and sha256, text_cleaning, the segmenter (the spaCy
version, the model and its version), the seed and the settings used
(partitions, bands, answers_per_band, answers_per_model, max_base_uses
and min_sentences), and these statistics. eligible gives, per
partition and dataset, the bases that pass the rule and the donors,
which counts every AI answer in that partition and dataset. candidates
gives, per partition, dataset and band, the number of base and donor
pairs that reach the band. rows counts the answers per partition,
dataset, band and model, mean_ai_fraction gives the mean AI share per
partition, dataset and band, most_base_uses is the most spliced answers
one base starts in a band, and answers_per_question counts the answers
per question across all bands. Counts per question and band come from the
question_id and style columns.
