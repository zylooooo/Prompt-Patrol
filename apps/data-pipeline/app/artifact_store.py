import hashlib
import logging
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from config import ARTIFACT_REPO_ID

logger = logging.getLogger(__name__)

_api = HfApi()


def push_artifact(local_path: Path, path_in_repo: str, commit_message: str) -> str:
    """Push a local file to the shared artifact repo, creating it if needed.

    Returns the resulting commit hash - the version id experiments should
    record as "which corpus version was this run trained/evaluated on."
    Requires an HF_TOKEN with write access to ARTIFACT_REPO_ID.
    """
    _api.create_repo(ARTIFACT_REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    commit_info = _api.upload_file(
        path_or_fileobj=str(local_path),
        path_in_repo=path_in_repo,
        repo_id=ARTIFACT_REPO_ID,
        repo_type="dataset",
        commit_message=commit_message,
    )
    return commit_info.oid


def pull_artifact(path_in_repo: str, local_dir: Path, revision: str | None = None) -> Path:
    """Download a file from the shared artifact repo.

    `revision` pins to an exact commit hash (a past version); omitted, this
    gets whatever is newest.
    """
    downloaded = hf_hub_download(
        repo_id=ARTIFACT_REPO_ID,
        filename=path_in_repo,
        repo_type="dataset",
        revision=revision,
        local_dir=str(local_dir),
    )
    return Path(downloaded)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_roundtrip(local_path: Path, path_in_repo: str, commit_message: str, download_dir: Path) -> bool:
    """Push a file, then pull back that exact commit, and check the bytes match.

    This is the PP-86 check folded into the push helper: pulling a past
    version by its id must reproduce byte-identical files, not just "close."
    """
    commit_hash = push_artifact(local_path, path_in_repo, commit_message)
    pulled_path = pull_artifact(path_in_repo, download_dir, revision=commit_hash)
    matches = _file_hash(local_path) == _file_hash(pulled_path)

    if matches:
        logger.info("Verified: %s round-trips byte-identical at commit %s", path_in_repo, commit_hash)
    else:
        logger.error("Mismatch: %s does NOT match what was pushed at commit %s", path_in_repo, commit_hash)

    return matches
