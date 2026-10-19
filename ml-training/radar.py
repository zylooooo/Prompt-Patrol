##  RADAR detector: loading and scoring, shared by the zero-shot and fine-tuning scripts

from __future__ import annotations

import argparse
import numpy as np
import torch

##  model on the hugging face hub (pinned to one revision so that every run scores with the same weights)
MODEL_ID = "TrustSafeAI/RADAR-Vicuna-7B"
REVISION = "4ff1f23a69a36aa1df47b0933be6279f1b896c9b"

##  RADAR has 2 outputs per answer (either AI or human)
##  the order comes from the model card's own example: log_softmax(logits)[:, 0] is 'AI-generated'
AI, HUMAN = 0, 1

## answers are short (99% are under ~105 words, RADAR's own limit is 512 tokens)
MAX_LEN = 256

##  human-written software-engineering prose from python's PEPs (2000-2001, public domain), topic-matched to PROBE_AI
##  sources: PEP 257, PEP 8, PEP 1, PEP 8, PEP 1 (https://peps.python.org)
##
##  PROBE_HUMAN:    paragraphs from the PEPs, unchanged
##  PROBE_AI:       an LLM's rewrite of each PEP paragraph, same topic and length, in the same order
PROBE_HUMAN = [
    "The docstring for a function or method should summarize its behavior and document its arguments, return "
    "value(s), side effects, exceptions raised, and restrictions on when it can be called (all if applicable). "
    "Optional arguments should be indicated. It should be documented whether keyword arguments are part of the "
    "interface.",
    "The preferred way of wrapping long lines is by using Python's implied line continuation inside parentheses, "
    "brackets and braces. Long lines can be broken over multiple lines by wrapping expressions in parentheses. "
    "These should be used in preference to using a backslash for line continuation.",
    "PEP stands for Python Enhancement Proposal. A PEP is a design document providing information to the Python "
    "community, or describing a new feature for Python or its processes or environment. The PEP should provide a "
    "concise technical specification of the feature and a rationale for the feature.",
    "Some teams strongly prefer a longer line length. For code maintained exclusively or primarily by a team that "
    "can reach agreement on this issue, it is okay to increase the line length limit up to 99 characters, provided "
    "that comments and docstrings are still wrapped at 72 characters.",
    "We intend PEPs to be the primary mechanisms for proposing major new features, for collecting community input "
    "on an issue, and for documenting the design decisions that have gone into Python. The PEP author is "
    "responsible for building consensus within the community and documenting dissenting opinions.",
]
PROBE_AI = [
    "A good function docstring should clearly describe what the function does, the parameters it accepts, and the "
    "value it returns. It is also helpful to mention any exceptions that may be raised and any side effects the "
    "function might have. Clear documentation makes code easier to understand, use, and maintain.",
    "When a line of code becomes too long, it is best to break it across multiple lines using parentheses, "
    "brackets, or braces. This approach takes advantage of Python's implicit line continuation and is generally "
    "preferred over using backslashes, which can be fragile and harder to read.",
    "A Python Enhancement Proposal, or PEP, is a design document that describes a new feature, process, or "
    "guideline for the Python community. Each PEP provides a clear technical specification along with the "
    "motivation behind the proposal, helping developers understand both what is being changed and why it matters.",
    "While shorter line lengths are often recommended, some teams prefer to allow longer lines to improve "
    "readability on modern displays. In such cases, it is important for the team to agree on a consistent limit, "
    "such as 99 characters, while still keeping comments and documentation wrapped at a shorter width.",
    "PEPs serve as the main way to propose significant changes to Python, gather feedback from the community, and "
    "record the reasoning behind design decisions. The author of a PEP is responsible for building consensus, "
    "addressing concerns raised during discussion, and documenting any differing opinions that emerge along the way.",
]

##  picks where the model runs: the NVIDIA GPU on the cluster, the Apple GPU on a Mac, or CPU
def default_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")

    if torch.backends.mps.is_available():
        return torch.device("mps")

    return torch.device("cpu")

##  downloads (for the first time only) and loads RADAR's tokenizer and model, and switches the model to eval mode
##  raises RuntimeError if any weight in the file wasn't loaded, or the model doesn't have exactly 2 outputs.
##  a weight that fails to load is replaced with random numbers and only prints a warning,
##  so a library update could otherwise give a model with a random classifier head without anyone noticing
##
##  device: where to run it (cuda/mps/cpu), leave empty to use default_device()
##  returns (model, tokenizer, device)
def load_radar(device: torch.device | str | None = None):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = torch.device(device) if device else default_device()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION)
    model, info = AutoModelForSequenceClassification.from_pretrained(MODEL_ID, revision=REVISION, output_loading_info=True)

    if failed := {k: sorted(v) for k, v in info.items() if v}:
        raise RuntimeError(f"RADAR weights did not load cleanly: {failed}")

    if model.config.num_labels != 2:
        raise RuntimeError(f"expected 2 outputs [AI, human], got {model.config.num_labels}")

    model.to(device).eval()
    return model, tokenizer, device

##  turns RADAR's 2 outputs into 1 number per answer (AI output minus human output)
##  sigmoid() of that number = RADAR's own softmax AI probability 
##  every script works with this 1 number, so the loss, temperature scaling, threshold and scores file work the same as desklib's
##
##  model:          RADAR, untouched or with LoRA
##  input_ids:       the tokenised answers, from encode()
##  attention_mask: marks which tokens are real and which are padding, from encode()
def radar_logit(model, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    out = model(input_ids=input_ids, attention_mask=attention_mask).logits.float()
    return out[:, AI] - out[:, HUMAN]

##  tokenises a batch of answers, padded to the longest answer in the batch and cut at max_len tokens
##
##  tokenizer:  radar's tokenizer, from load_radar()
##  texts:      the answers in this batch
##  device:     where to put the result
##  max_len:    the longest an answer can be, in tokens
##  returns (input_ids, attention_mask)
def encode(tokenizer, texts, device: torch.device, max_len: int = MAX_LEN):
    enc = tokenizer([str(t) for t in texts], padding=True, truncation=True, max_length=max_len, return_tensors="pt")
    return enc["input_ids"].to(device), enc["attention_mask"].to(device)

##  scores a list of answers and returns one logit per answer (same order as text)
##  answers are scored in batches sorted shortest-first (less padding = faster), then returned to original order
##
##  model:      RADAR, untouched, or with LoRA 
##  tokenizer:  RADAR's tokenizer
##  texts:      the answers to score
##  device:     where the model is ran
##  batch_size: answers scored at once
##  max_len:    longest an answer can be (in tokens)
@torch.no_grad()
def predict_logits(model, tokenizer, texts, device: torch.device, batch_size: int = 64, max_len: int = MAX_LEN) -> np.ndarray:
    model.eval()
    texts = np.asarray([str(t) for t in texts], dtype=object)
    order = np.argsort([len(t) for t in texts], kind="stable")
    out = np.empty(len(texts), dtype=np.float64)

    for i in range(0, len(texts), batch_size):
        idx = order[i:i + batch_size]
        ids, mask = encode(tokenizer, texts[idx], device, max_len)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out[idx] = radar_logit(model, ids, mask).cpu().numpy()

    return out

##  PP-550 sanity check, run with `python radar.py --check`. exits with "CHECK FAILED" and the reasons if 1, 2 or 3 fails
##  the checks:
##      1. every weight loaded (done inside load_radar(), which raises before anything is scored)
##      2. the 1-number logit equals the authors' own formula, softmax(logits)[:, AI], on 16 validation answers (allowed gap 1e-3)
##      3. scores come back in the original order: shuffled input, batch size 7, must give the same scores as in order, batch size 64
##      4. PEP probe -> prints RADAR's AI probability for the PEP paragraphs and their AI rewrites.
##         information only: untouched RADAR scores both ~0.997, so it can't confirm the label order
##      5. zero-shot on the validation split -> prints the mean AI probability and AUROC. information only
##  the label order (AI = output 0) is taken from the authors' code, see the note on AI, HUMAN at the top
##
##  n:      validation rows to score in 5, half AI and half human so the two means are comparable (0 = every row)
##  seed:   which random rows are picked
##  device: where to run it (cuda/mps/cpu), leave empty to use default_device()
def check(n: int, seed: int, device: str | None) -> None:
    from scipy.special import expit
    from sklearn.metrics import roc_auc_score
    from combined_data import load_combined

    model, tokenizer, device = load_radar(device)
    print(f"1. weights: every weight loaded, {model.config.num_labels} outputs, on {device}")
    problems = []

    val = load_combined()["val"]
    if n:
        per = min(n // 2, int(val["label"].value_counts().min()))
        val = val.groupby("label").sample(n=per, random_state=seed).reset_index(drop=True)
    texts = val["answer"].to_numpy()

    sample = texts[:16]
    with torch.no_grad():
        ids, mask = encode(tokenizer, sample, device)
        reference = torch.softmax(model(input_ids=ids, attention_mask=mask).logits.float(), -1)[:, AI].cpu().numpy()
    gap = float(np.abs(expit(predict_logits(model, tokenizer, sample, device)) - reference).max())
    print(f"2. formula: max |sigmoid(logit) - softmax[AI]| = {gap:.2e}")

    if gap > 1e-3:
        problems.append(f"sigmoid(logit) differs from the authors' AI probability by {gap:.2e}")

    logits = predict_logits(model, tokenizer, texts, device)
    shuffle = np.random.default_rng(seed).permutation(len(texts))
    reordered = np.empty_like(logits)
    reordered[shuffle] = predict_logits(model, tokenizer, texts[shuffle], device, batch_size=7)
    drift = float(np.abs(logits - reordered).max())
    print(f"3. order: max difference between in-order and shuffled scoring = {drift:.2e}")

    if drift > 1e-3:
        problems.append(f"scores change with input order or batch size by {drift:.2e}: rows are being mixed up")

    probe = expit(predict_logits(model, tokenizer, PROBE_HUMAN + PROBE_AI, device))
    human_p, ai_p = probe[:len(PROBE_HUMAN)], probe[len(PROBE_HUMAN):]
    print(f"4. PEP probe (info only): human {np.round(human_p, 3)}, AI rewrites {np.round(ai_p, 3)}, "
          f"AI higher in {int((ai_p > human_p).sum())} of {len(ai_p)} pairs")

    y, prob = val["label"].to_numpy(), expit(logits)
    print(f"5. zero-shot on {len(val)} val answers (info only): mean AI probability {prob[y == 1].mean():.3f} on AI answers, "
          f"{prob[y == 0].mean():.3f} on human answers, AUROC {roc_auc_score(y, logits):.3f}")

    if problems:
        raise SystemExit("CHECK FAILED\n- " + "\n- ".join(problems))
    print("CHECK PASSED: weights loaded, the logit matches the authors' formula, and scores stay attached to their answers")

##  command line entry point
##      python radar.py --check            -> PP-550 check, plus 200 validation answers
##      python radar.py --check --n 0      -> every validation answer
def main() -> None:
    ap = argparse.ArgumentParser(description="RADAR loading and scoring. Run with --check for the PP-550 sanity check.")
    ap.add_argument("--check", action="store_true", help="run the PP-550 label-order check")
    ap.add_argument("--n", type=int, default=200, help="validation rows to score; 0 = all")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    args = ap.parse_args()

    if not args.check:
        ap.print_help()
        return

    check(args.n, args.seed, args.device)

if __name__ == "__main__":
    main()
