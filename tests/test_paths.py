import pytest

from issue_proof.collector import ensure_output_dir, safe_output_file
from issue_proof.errors import OutputPathError


def test_output_path_rejects_traversal_and_windows_absolute(tmp_path) -> None:
    root = ensure_output_dir(tmp_path / "path-test-output")
    with pytest.raises(OutputPathError):
        safe_output_file(root, "../outside.txt")
    with pytest.raises(OutputPathError):
        safe_output_file(root, r"C:\outside.txt")
    with pytest.raises(OutputPathError):
        safe_output_file(root, r"\server\share\outside.txt")
    target = safe_output_file(root, "nested/report.json")
    assert target.parent == root / "nested"
