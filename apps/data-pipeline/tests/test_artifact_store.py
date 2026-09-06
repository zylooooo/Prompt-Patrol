from unittest.mock import MagicMock, patch

from artifact_store import push_artifact, verify_roundtrip


def test_push_artifact_creates_repo_and_uploads(tmp_path):
    local_file = tmp_path / "data.parquet"
    local_file.write_bytes(b"fake parquet bytes")

    with (
        patch("artifact_store._api.create_repo") as mock_create_repo,
        patch("artifact_store._api.upload_file") as mock_upload_file,
    ):
        mock_upload_file.return_value = MagicMock(oid="abc123")

        commit_hash = push_artifact(local_file, "mohler/splits/latest.parquet", "test push")

    assert commit_hash == "abc123"
    mock_create_repo.assert_called_once()
    assert mock_create_repo.call_args.kwargs["private"] is True
    assert mock_create_repo.call_args.kwargs["exist_ok"] is True

    upload_kwargs = mock_upload_file.call_args.kwargs
    assert upload_kwargs["path_in_repo"] == "mohler/splits/latest.parquet"
    assert upload_kwargs["commit_message"] == "test push"


def test_verify_roundtrip_true_when_pulled_file_matches(tmp_path):
    local_file = tmp_path / "data.parquet"
    local_file.write_bytes(b"identical content")

    # Simulate the "pull" landing an identical copy in the download dir.
    pulled_file = tmp_path / "downloaded" / "data.parquet"
    pulled_file.parent.mkdir()
    pulled_file.write_bytes(b"identical content")

    with (
        patch("artifact_store.push_artifact", return_value="commit123"),
        patch("artifact_store.pull_artifact", return_value=pulled_file),
    ):
        result = verify_roundtrip(local_file, "mohler/splits/latest.parquet", "test push", tmp_path / "downloaded")

    assert result is True


def test_verify_roundtrip_false_when_pulled_file_differs(tmp_path):
    local_file = tmp_path / "data.parquet"
    local_file.write_bytes(b"original content")

    pulled_file = tmp_path / "downloaded" / "data.parquet"
    pulled_file.parent.mkdir()
    pulled_file.write_bytes(b"corrupted content")

    with (
        patch("artifact_store.push_artifact", return_value="commit123"),
        patch("artifact_store.pull_artifact", return_value=pulled_file),
    ):
        result = verify_roundtrip(local_file, "mohler/splits/latest.parquet", "test push", tmp_path / "downloaded")

    assert result is False
