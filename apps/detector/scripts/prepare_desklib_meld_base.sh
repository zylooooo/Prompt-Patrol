#!/usr/bin/env bash
# Stages MELD's base model for Dockerfile.desklib-meld-base: copies the revision the release bundle pins out of the
# local Hugging Face cache into model/meld-base/ (real files, not cache symlinks), checks the weights' hash, and
# records the revision. MELD's repo is gated, so the cache is the source, not a download.
#
#   cd apps/detector && ./scripts/prepare_desklib_meld_base.sh
#
# Needs: the bundle in model/desklib-meld/ (ml-training: release_desklib_meld.py --fetch) and MELD at that revision
# in the HF cache ($HF_HOME, default ~/.cache/huggingface). model/meld-base/ is git-ignored (~3.8GB).
set -euo pipefail

cd "$(dirname "$0")/.."
die() { echo "error: $*" >&2; exit 1; }

BUNDLE=model/desklib-meld
DEST=model/meld-base
[ -f "$BUNDLE/desklib-meld.json" ] || die "no $BUNDLE/desklib-meld.json. Fetch the bundle first:
  cd ml-training && .venv/bin/python release_desklib_meld.py --fetch --run-id 04da6e99ed3e41c9ae6742ae5c0fcbf1"

REV=$(python3 -c "import json; print(json.load(open('$BUNDLE/desklib-meld.json'))['meld']['base_revision'])")
REPO_DIR="${HF_HOME:-$HOME/.cache/huggingface}/hub/models--anon-review-meld-2026--meld"
SRC="$REPO_DIR/snapshots/$REV"
[ -d "$SRC" ] || die "MELD@$REV is not in the HF cache ($SRC). The repo is gated: download it with an approved token,
  or copy the snapshot from a machine that has it (e.g. the GPU cluster)."

# The weights are an LFS file, so the cache names its blob by the file's sha256: check the copy against it
EXPECTED=$(basename "$(readlink "$SRC/model.safetensors")")

echo "copying MELD@${REV:0:12} from $SRC ..."
rm -rf "$DEST"
mkdir -p "$DEST"
cp -RL "$SRC"/. "$DEST"/
rm -rf "$DEST/__pycache__"

ACTUAL=$(shasum -a 256 "$DEST/model.safetensors" | cut -d' ' -f1)
[ "$ACTUAL" = "$EXPECTED" ] || die "model.safetensors sha256 $ACTUAL does not match the cache's $EXPECTED"
echo "$REV" > "$DEST/REVISION"

echo "staged $(du -sh "$DEST" | cut -f1) in $DEST (weights sha256 OK). Next:
  docker build -f Dockerfile.desklib-meld-base -t prompt-patrol-detector-base:desklib-meld-v1 ."
