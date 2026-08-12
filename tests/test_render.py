from issue_proof.render import render_report


def test_render_has_stable_sections_and_sanitized_text(tmp_path) -> None:
    from issue_proof.collector import collect_from_issue_file

    issue = tmp_path / "issue.md"
    issue.write_text("# Render bug\n\nThe body.\n", encoding="utf-8")
    report, _, _ = collect_from_issue_file(
        issue_file=issue, repo_root=tmp_path, command=None, output_dir=tmp_path / "out"
    )
    rendered = render_report(report)
    assert rendered.startswith("# Issue Proof Evidence\n")
    assert (
        rendered.index("## Issue")
        < rendered.index("## Repository")
        < rendered.index("## Execution")
    )
    assert "## Outcomes" in rendered
    assert "The body." in rendered
