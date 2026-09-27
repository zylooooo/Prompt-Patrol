#!/bin/bash
# One-time setup for each person on the shared cluster login. Run it on the
# login node (not with sbatch):
#
#   bash /path/to/setup_me.sh <yourname>
#
# It clones the repo into ~/<yourname>/, asks for YOUR DagsHub username and
# access token, writes your git-ignored credential files
#
# The cluster login is shared, so anyone on it can read your files. Use a
# DagsHub token you can revoke, and revoke it when you are done.
set -e

NAME=${1:?usage: bash setup_me.sh <yourname>}

mkdir -p "$HOME/$NAME"
cd "$HOME/$NAME"
[ -d Prompt-Patrol ] || git clone https://github.com/zylooooo/Prompt-Patrol.git
cd Prompt-Patrol

module purge
module load Python/3.11.11-GCCcore-13.3.0
source "$HOME/venvs/prompt-patrol/bin/activate"

read -r -p "DagsHub username: " U
read -r -s -p "DagsHub token: " T; echo

cat > ml-training/.env << EOF
MLFLOW_TRACKING_USERNAME=$U
MLFLOW_TRACKING_PASSWORD=$T
DAGSHUB_REPO_OWNER=zylooooo
DAGSHUB_REPO_NAME=Prompt-Patrol
EOF
chmod 600 ml-training/.env

dvc remote modify --local origin auth basic
dvc remote modify --local origin user "$U"
dvc remote modify --local origin password "$T"
dvc pull

echo "Done. Next: cd ~/$NAME && sbatch Prompt-Patrol/ml-training/cluster/smoke.sh"
