import pytest

from issue_proof.codex.agents import collect_agents
from issue_proof.errors import OutputPathError


def test_agents_reports_nested_precedence_and_missing_target(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "AGENTS.md").write_text("root guidance\n", encoding="utf-8")
    (tmp_path / "src" / "AGENTS.md").write_text("ignored by override\n", encoding="utf-8")
    (tmp_path / "src" / "AGENTS.override.md").write_text(
        "nested token=sk-proj-not-real\n", encoding="utf-8"
    )
    scan = collect_agents(tmp_path, "src/missing file.py")
    assert scan.target_exists is False
    assert [item["relative_path"] for item in scan.files] == [
        "AGENTS.md",
        "src/AGENTS.override.md",
    ]
    assert scan.files[0]["content"] is None
    assert scan.files[1]["sha256"]
    assert scan.files[1]["scope"] == "directory:src"

    with_content = collect_agents(tmp_path, "src/missing file.py", include_content=True)
    assert "[REDACTED]" in with_content.files[1]["content"]


def test_agents_rejects_traversal(tmp_path) -> None:
    with pytest.raises(OutputPathError):
        collect_agents(tmp_path, "../outside.py")


@pytest.mark.parametrize(
    "target",
    [r"C:drive-relative.txt", r"\rooted.txt", r"\\?\C:\device\target.txt"],
)
def test_agents_rejects_drive_qualified_rooted_and_device_targets(tmp_path, target) -> None:
    with pytest.raises(OutputPathError):
        collect_agents(tmp_path, target)


def test_agents_records_symlink_without_following_when_supported(tmp_path) -> None:
    outside = tmp_path.parent / "outside-agents.md"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "AGENTS.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "Windows did not grant symlink creation permission; symlink behavior was not tested: "
            f"{exc}"
        )
    scan = collect_agents(tmp_path)
    assert scan.files[0]["symlink"] is True
    assert scan.files[0]["readable"] is False
    assert any("symlink" in warning for warning in scan.warnings)
