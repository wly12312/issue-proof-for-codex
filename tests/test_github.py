import pytest

from issue_proof.github import parse_issue_url


def test_parse_issue_url_canonicalizes_and_rejects_credentials() -> None:
    assert parse_issue_url("https://github.com/OWNER/REPO/issues/001") == (
        "https://github.com/OWNER/REPO/issues/1"
    )
    with pytest.raises(ValueError):
        parse_issue_url("https://alice:secret@github.com/OWNER/REPO/issues/1")
    with pytest.raises(ValueError):
        parse_issue_url("http://github.com/OWNER/REPO/issues/1")
    with pytest.raises(ValueError):
        parse_issue_url("https://github.com/OWNER/REPO/issues/1?token=secret")
