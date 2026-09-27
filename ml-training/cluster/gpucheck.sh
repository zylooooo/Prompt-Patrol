#!/bin/bash
# Diagnostic job: which GPU/driver/CUDA a job lands on, and whether compute
# nodes can reach the sites we need. Ten minutes at most.
#
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/gpucheck.sh
#SBATCH --job-name=gpu-check
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=%u.%j.out

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0

hostname
nvidia-smi
nvcc --version | tail -2
for u in huggingface.co pypi.org github.com dagshub.com; do
  echo -n "$u: "; curl -sS -m 10 -o /dev/null -w "%{http_code}\n" https://$u 2>&1 | tail -1
done
