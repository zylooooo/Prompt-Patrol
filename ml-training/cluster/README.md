# Training on the SCIS GPU cluster

How to run `ml-training` experiments on the GPU cluster.

## What you need

- The SMU GlobalProtect VPN, connected, with a healthy ClearPass.
- The cluster login details.
- Your **own** DagsHub account and a personal access token 
  (DagsHub, Settings, Tokens). Make one for the cluster.

## Rules that matter

- **Max one running job for the whole group** 
- **Max 2 submitted jobs** 
- **Never train on the login node.** It has no GPU and heavy work there can be killed.
- **Nothing is backed up.** Keep code in git. Files in scratch older than 30 days are
  deleted.
- **Do not `pip install` into the shared environment** (`~/venvs/prompt-patrol`) without
  telling the group, because it changes everyone's environment.

## One-time setup

Each person works in their own folder, `~/<yourname>/`, and never in someone else's.
The Python environment is already built and shared, so you do not reinstall anything.

1. Connect the VPN and `ssh` to the cluster.
2. Get the setup script and run it (it clones the repo into `~/<yourname>/`, asks for
   your DagsHub username and token, writes your `.env` and DVC credentials, and runs
   `dvc pull`):

   ```bash
   curl -sO https://raw.githubusercontent.com/zylooooo/Prompt-Patrol/main/ml-training/cluster/setup_me.sh
   bash setup_me.sh <yourname>
   ```

## Run the smoke test

Not required to finish setup — `setup_me.sh` already proves your clone, credentials
and `dvc pull` work. Run this if you want to confirm your own MLflow logging works,
or before your first real experiment.

```bash
cd ~/<yourname>
myqueue                                                     # is anything running?
sbatch Prompt-Patrol/ml-training/cluster/smoke.sh
```

The log is written to `~/<yourname>/<user>.<jobid>.out`. A good run ends with a
`test: {...}` line and a DagsHub run URL, and the run appears under experiment
`trial-run` on DagsHub. The `TRIAL` numbers are a pipeline check only (the trial corpus
has known label leaks), so never cite them.

To run a different config from `experiments.py`, pass its name:
`sbatch Prompt-Patrol/ml-training/cluster/smoke.sh ROBERTA_LORA`.

Set your own `owner=` on your configs so runs are attributable

## Every session

```bash
module load Python/3.11.11-GCCcore-13.3.0        # must come BEFORE activating the venv
source ~/venvs/prompt-patrol/bin/activate
```

Batch scripts do this themselves. You only need it for interactive commands such as
`dvc pull`.

## Useful commands

| Command | What it does |
|---|---|
| `myinfo` | Partition, QOS limits and your quota |
| `myqueue` | Your group's pending and running jobs |
| `myjob <jobid>` | Details of a running or just-finished job |
| `mypastjob <days>` | Job history, up to 30 days |
| `sbatch <script>` / `scancel <jobid>` | Submit or cancel (never `scancel -u`, it cancels teammates' jobs) |
| `tail -f <log>` | Follow a job's log |
| `du -sh ~/* ~/.cache/* 2>/dev/null \| sort -h \| tail` | What is using your home quota |

## The environment

Built by `setup_env.sh` from `requirements.txt`, using the `Python/3.11.11-GCCcore-13.3.0`
module. Verified on 2026-09-26: RTX 3090 (24 GB), driver 590.48.01 (supports up to
CUDA 13.1), `torch 2.14.0+cu130`, `transformers 5.16.1`, `peft 0.20.0`. Compute nodes can
reach huggingface.co, pypi.org, github.com and dagshub.com. Other nodes in the partition
may carry different GPUs, so check `nvidia-smi` in your own logs.

`env-record/` holds the exact `pip-freeze.txt` and `nvidia-smi.txt` from that build.
`setup_env.sh` uses the freeze as a constraints file, so rebuilding gives the same
versions. To test a clean install without touching the shared environment:

```bash
cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/setup_env.sh $HOME/venvs/verify
```

The log ends with a diff against the committed freeze (`IDENTICAL` means it reproduced).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `error while loading shared libraries: libpython3.11.so` | Run `module load Python/3.11.11-GCCcore-13.3.0` before activating the venv |
| `dvc pull` returns 401 or 403 | Accept the DagsHub invite, and check the token and username |
| Job stays pending | Someone else's job is running (limit is one per group), or the node is busy. See `myjob <jobid>` |
| `Connection closed` after a while | Idle auto-logout. Running jobs are not affected |
| Job fails instantly on `sbatch` | Check the `--partition/--account/--qos` lines match `myinfo` |
