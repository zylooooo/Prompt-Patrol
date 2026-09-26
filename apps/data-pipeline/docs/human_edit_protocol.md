# Editing protocol: human-edited AI answers (PP-101)

The detector has to handle the realistic case of a student who takes an AI
answer and touches it up before submitting. This protocol is how team
members make the **genuine** edits. An LLM later copies the patterns in
these edits at scale (the **simulated** subset), so the edits need to look
like what a student would really do.

## Size of the genuine subset

- 5 editors x 10 answers each = **50 genuine edits** (proposed default,
  confirm with the team before sending the sheets out).
- Each answer goes to exactly one editor. Every editor gets a mix of
  generators and quality tiers.

## What you get

One CSV file with your name, for example `faheem.csv`. Open it in Excel,
Numbers or Google Sheets. Each row has:

| Column | What to do |
|---|---|
| `edit_id` | Leave alone |
| `question` | Read it |
| `original_answer` | Leave alone, this is what the AI wrote |
| `edited_answer` | Starts as a copy of the original. **Edit this one** |
| `edit_types` | List the edit types you used, comma separated |
| `notes` | Optional, anything worth flagging |

Save it as CSV with the same file name and send it back.

## Allowed edit types

Use one or more of these, and write the ones you used in `edit_types`
exactly as spelled here:

| Type | What it means | Example |
|---|---|---|
| `reorder` | Move a sentence or phrase to a different place | Put the last sentence first |
| `delete` | Cut a sentence or part of one | Drop an extra example or a closing line |
| `reword` | Change some words into your own | "utilizes" to "uses", "In conclusion" to "So" |
| `fact_tweak` | Change a small detail | Swap a term, a number or an example for a similar one |

Nothing outside these four. Do not add new sentences or new ideas.

## How to edit

- **Edit the way a student would, not to improve the answer.** You are not
  grading or fixing it. A wrong answer stays wrong unless a small
  `fact_tweak` changes a detail.
- Make a few quick changes, the kind of thing you would do in a couple of
  minutes before submitting. Most of the AI's wording should still be there.
- Vary what you do across your rows. Not every row needs every edit type.
- Write the way you normally would, including casual wording. Do not
  polish grammar or spelling beyond what you would really bother with.
- Do not rewrite from scratch. If you would rather rewrite the whole
  thing, make a smaller edit instead.
- Do not paste the answer into another AI tool.
- Every row must change. A row left identical to the original is dropped.

## What happens next

1. The returned sheets are read back in and checked: unchanged rows and
   unknown edit types are reported.
2. The edit types you used, and some of your edits as examples, become the
   prompt for the simulated subset. The simulation copies real behaviour,
   not a guess.
3. The two subsets are compared on how much text changed (word-level edit
   distance). The comparison goes into the dataset card so a reader can
   judge how faithful the simulation is.
4. Every sample is labelled `human_edited`, keeps a link to its source
   answer, and carries `edit_source` of `genuine` or `simulated`. A
   simulated sample is never presented as genuine.
