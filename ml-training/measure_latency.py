## CPU scoring speed and memory for desklib, RADAR and both together (PP-559): can the detector afford the desklib + RADAR combination?

from __future__ import annotations

import argparse
import multiprocessing as mp
import resource
import sys
import time

import numpy as np

##  the detector scores one answer per request, on CPU, with no padding, cut at 256 tokens (apps/detector/app/desklib.py).
##  the timings copy that: batch size 1, the same cut, on 1 and 2 threads (the Fargate task has 1-2 vCPU)
MAX_TOKENS = 256
CONFIGS = ("desklib", "radar", "both")

##  the process's peak memory so far, in MB. macOS reports bytes, Linux reports KB
def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3

##  the memory the process holds right now, in MB: what a running detector keeps using after loading.
##  the peak can be much higher, because desklib briefly holds two copies of its weights while loading
def current_rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1e6

##  loads desklib on CPU the way eval_desklib_zeroshot.py does (base weights: the detector merges its LoRA adapter into
##  the same layers, so the work per answer is the same) and returns a function text -> logit
def load_desklib():
    import torch
    from eval_desklib_zeroshot import Scorer

    scorer = Scorer(device="cpu")
    model, tokenizer = scorer.model, scorer.tokenizer

    @torch.no_grad()
    def score(text: str) -> float:
        enc = tokenizer(text, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
        return float(model(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"])["logits"].item())

    return score

##  loads RADAR on CPU through radar.py and returns a function text -> logit
def load_radar():
    import torch
    import radar

    model, tokenizer, device = radar.load_radar("cpu")

    @torch.no_grad()
    def score(text: str) -> float:
        enc = tokenizer(text, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
        return float(radar.radar_logit(model, enc["input_ids"], enc["attention_mask"]).item())

    return score

##  one measurement, run in its own fresh process so the memory reading belongs to this setup alone.
##  memory is read after scoring, because the weights are only fully paged into memory once they are used
##  steps: limit torch to `threads` CPU threads, load the model(s), score `warmup` answers untimed (the first calls are slow
##  while torch sets up), then time each of `n` answers one at a time. "both" scores desklib then RADAR, like a detector
##  that runs the two in a row and averages them (the averaging itself is negligible)
##
##  config:     desklib/radar/both
##  threads:    CPU threads torch may use
##  texts:      answers to score
##  warmup:     untimed answers first
##  out:        queue the result dict is put on
def worker(config: str, threads: int, texts: list[str], warmup: int, out) -> None:
    import torch

    torch.set_num_threads(threads)
    base = peak_rss_mb()
    scorers = []
    if config in ("desklib", "both"):
        scorers.append(load_desklib())
    if config in ("radar", "both"):
        scorers.append(load_radar())

    for text in texts[:warmup]:
        for s in scorers:
            s(text)

    times = []
    for text in texts[warmup:]:
        start = time.perf_counter()
        for s in scorers:
            s(text)
        times.append((time.perf_counter() - start) * 1000)

    times = np.array(times)
    out.put({"config": config, "threads": threads, "n": len(times), "p50_ms": float(np.percentile(times, 50)),
             "p95_ms": float(np.percentile(times, 95)), "mean_ms": float(times.mean()),
             "answers_per_s": float(1000 / times.mean()), "model_mb": peak_rss_mb() - base, "peak_mb": peak_rss_mb(),
             "steady_mb": current_rss_mb()})

##  the answers to time: real test answers of at least 10 words (what the app scores), a fixed random sample
##
##  n:      how many
##  seed:   which ones
def sample_texts(n: int, seed: int) -> list[str]:
    from combined_data import load_corpus

    test = load_corpus("extended")["test"]
    test = test[test["n_words"] >= 10]
    return test.sample(min(n, len(test)), random_state=seed)["answer"].astype(str).tolist()

##  runs every config x thread count, each in a fresh process, and prints one table plus how "both" compares to desklib alone.
##  Apple CPUs are faster than Fargate's, so read the absolute times as a lower bound and the both/desklib ratio as the result;
##  the memory figures carry over (weights take the same space on any CPU)
def main() -> None:
    ap = argparse.ArgumentParser(description="CPU latency and memory: desklib, RADAR, and both (PP-559).")
    ap.add_argument("--threads", default="1,2", help="CPU thread counts to test, e.g. 1,2 for Fargate's 1-2 vCPU")
    ap.add_argument("--configs", default=",".join(CONFIGS), help="desklib,radar,both")
    ap.add_argument("--n", type=int, default=100, help="answers timed per setup")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    threads = [int(t) for t in args.threads.split(",") if t]
    configs = [c for c in args.configs.split(",") if c]
    if bad := set(configs) - set(CONFIGS):
        raise SystemExit(f"unknown config(s) {sorted(bad)}; choose from {CONFIGS}")

    texts = sample_texts(args.n + args.warmup, args.seed)
    print(f"{len(texts) - args.warmup} answers timed per setup (+{args.warmup} warm-up), median {np.median([len(t.split()) for t in texts]):.0f} words")

    ctx = mp.get_context("spawn")
    rows = []
    for t in threads:
        for c in configs:
            out = ctx.Queue()
            p = ctx.Process(target=worker, args=(c, t, texts, args.warmup, out))
            p.start()
            rows.append(out.get())
            p.join()
            r = rows[-1]
            print(f"  {c:<8} {t} thread(s): p50 {r['p50_ms']:7.1f} ms  p95 {r['p95_ms']:7.1f} ms  "
                  f"{r['answers_per_s']:5.1f} answers/s  in use {r['steady_mb']:6.0f} MB  peak {r['peak_mb']:6.0f} MB", flush=True)

    print("\n=== both vs desklib alone ===")
    for t in threads:
        d = next((r for r in rows if r["config"] == "desklib" and r["threads"] == t), None)
        b = next((r for r in rows if r["config"] == "both" and r["threads"] == t), None)
        if d and b:
            print(f"  {t} thread(s): {b['p50_ms'] / d['p50_ms']:.2f}x the time per answer, memory in use "
                  f"{d['steady_mb'] / 1000:.1f} GB -> {b['steady_mb'] / 1000:.1f} GB (peak while loading {b['peak_mb'] / 1000:.1f} GB)")


if __name__ == "__main__":
    main()
