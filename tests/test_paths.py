import os
import stat
import subprocess

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
        safe_output_file(root, r"C:relative.txt")
    with pytest.raises(OutputPathError):
        safe_output_file(root, r"\server\share\outside.txt")
    target = safe_output_file(root, "nested/report.json")
    assert target.parent == root / "nested"


@pytest.mark.skipif(os.name != "nt", reason="Windows-only reparse-point contract")
def test_output_directory_rejects_windows_junction(tmp_path) -> None:
    target = tmp_path / "junction target"
    junction = tmp_path / "junction output"
    target.mkdir()
    environment = os.environ.copy()
    environment["ISSUE_PROOF_JUNCTION"] = str(junction)
    environment["ISSUE_PROOF_TARGET"] = str(target)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "New-Item -ItemType Junction -Path $env:ISSUE_PROOF_JUNCTION "
                "-Target $env:ISSUE_PROOF_TARGET | Out-Null"
            ),
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            "Windows junction creation failed; reparse behavior was not tested: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    attributes = junction.lstat().st_file_attributes
    assert attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT

    with pytest.raises(OutputPathError, match="reparse"):
        ensure_output_dir(junction)
