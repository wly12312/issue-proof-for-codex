import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import issue_proof

EXPECTED_VERSION = "0.1.3"


def test_skill_frontmatter_and_resources_follow_contract() -> None:
    root = Path(__file__).parents[1]
    skill = root / "skills" / "reproduce-github-issue" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter, body = text.split("\n---\n", 1)
    assert set(frontmatter.splitlines()) >= {
        "---",
        "name: reproduce-github-issue",
    }
    assert "description:" in frontmatter
    assert "metadata:" not in frontmatter
    assert len(text.splitlines()) < 300
    assert "[safety-policy.md](references/safety-policy.md)" in body
    assert "[evidence-model.md](references/evidence-model.md)" in body
    assert "[receipt-model.md](references/receipt-model.md)" in body
    ui = (skill.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "display_name:" in ui and "short_description:" in ui and "$reproduce-github-issue" in ui
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "oss-issue-proof"
    assert manifest["skills"] == "./skills/"
    assert re.fullmatch(r"[a-z0-9-]+", manifest["name"])
    prompts = manifest["interface"]["defaultPrompt"]
    assert isinstance(prompts, list)
    assert 0 < len(prompts) <= 3
    assert all(isinstance(prompt, str) and prompt.strip() for prompt in prompts)
    assert all(len(prompt) <= 128 for prompt in prompts)


def test_skill_standalone_references_and_installed_cli_delegate(tmp_path) -> None:
    root = Path(__file__).parents[1]
    source_skill = root / "skills" / "reproduce-github-issue"
    standalone_skill = tmp_path / "reproduce-github-issue"
    shutil.copytree(source_skill, standalone_skill)

    assert not (tmp_path / "docs").exists()
    markdown_link = re.compile(r"\]\(([^)#]+)(?:#[^)]*)?\)")
    for markdown in standalone_skill.rglob("*.md"):
        for reference in markdown_link.findall(markdown.read_text(encoding="utf-8")):
            if reference.startswith(("http://", "https://", "mailto:")):
                continue
            assert (markdown.parent / reference).resolve().is_file(), reference

    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        [str(Path(sys.executable).parent), environment.get("PATH", "")]
    )
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(standalone_skill / "scripts" / "run_issue_proof.py"), "--version"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == EXPECTED_VERSION
    script = (standalone_skill / "scripts" / "run_issue_proof.py").read_text(encoding="utf-8")
    assert "sys.path" not in script
    assert ".parents" not in script
    assert 'sys.executable, "-I", "-m", "issue_proof"' in script
    assert "shutil.which" not in script


def test_skill_delegate_uses_consumer_interpreter_when_cli_is_not_on_path(tmp_path) -> None:
    root = Path(__file__).parents[1]
    source_skill = root / "skills" / "reproduce-github-issue"
    standalone_skill = tmp_path / "reproduce-github-issue"
    shutil.copytree(source_skill, standalone_skill)
    environment = os.environ.copy()
    environment["PATH"] = ""
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(standalone_skill / "scripts" / "run_issue_proof.py"), "--version"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == EXPECTED_VERSION


def test_skill_delegate_does_not_execute_checkout_local_cli_lookalike(tmp_path) -> None:
    root = Path(__file__).parents[1]
    standalone_skill = tmp_path / "reproduce-github-issue"
    shutil.copytree(root / "skills" / "reproduce-github-issue", standalone_skill)
    shutil.copy2(sys.executable, tmp_path / "issue-proof.exe")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(standalone_skill / "scripts" / "run_issue_proof.py"), "--version"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == EXPECTED_VERSION


def test_release_metadata_matches_current_v0_1_3_tag() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    artifact = (root / ".github" / "workflows" / "codex-receipt-artifact.yml").read_text(
        encoding="utf-8"
    )
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")

    assert project["project"]["version"] == EXPECTED_VERSION
    assert issue_proof.__version__ == EXPECTED_VERSION
    assert plugin["version"] == EXPECTED_VERSION

    assert "permissions:\n  contents: read\n\njobs:" in ci
    assert "python-version: ['3.11', '3.12', '3.14']" in ci
    assert "runs-on: windows-latest" in ci
    assert "defaults:\n      run:\n        shell: pwsh" in ci
    assert ci.count("persist-credentials: false") == 1
    assert "ruff format --check ." in ci
    assert "ruff check ." in ci
    assert "pytest --basetemp $baseTemp --cov=issue_proof --cov-report=term-missing" in ci
    assert 'Join-Path $env:RUNNER_TEMP "Issue Proof 路径"' in ci
    assert "python -m issue_proof codex doctor" in ci
    assert "python -m build" in ci
    assert "ubuntu-latest" not in ci

    assert "permissions:\n  contents: read\n  actions: read\n\njobs:" in artifact
    assert "runs-on: windows-latest" in artifact
    assert "defaults:\n      run:\n        shell: pwsh" in artifact
    assert artifact.count("persist-credentials: false") == 1
    assert "shell: pwsh" in artifact
    assert "shell: bash" not in artifact
    assert "$GITHUB_OUTPUT" not in artifact
    assert "$env:GITHUB_OUTPUT" in artifact
    forbidden_run = re.compile(
        r"(?m)^\s*-\s+run:\s+(?:bash|find|test)\b|^\s{10}(?:bash|find|test)(?:\s|$)"
    )
    assert forbidden_run.search(ci) is None
    assert forbidden_run.search(artifact) is None
    assert "$traces.Count -ne 1" in artifact
    assert "$reports.Count -ne 1" in artifact
    assert "Select-Object -First 1" not in artifact
    assert "TRACE_PATH: ${{ steps.trace.outputs.path }}" in artifact
    assert "BASELINE_PATH: ${{ steps.baseline.outputs.path }}" in artifact
    assert '--trace "$env:TRACE_PATH"' in artifact
    assert '--baseline "$env:BASELINE_PATH"' in artifact
    assert '--trace "${{ steps.trace.outputs.path }}"' not in artifact
    assert '--baseline "${{ steps.baseline.outputs.path }}"' not in artifact
    assert "include-hidden-files: true" in artifact

    actions = re.findall(r"uses:\s+([^#\s]+)", ci + "\n" + artifact)
    assert actions
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action) for action in actions)

    assert ".envrc" in gitignore
    assert "*.jsonl" in gitignore
    assert "!examples/codex-maintenance/trace-order-a.jsonl" in gitignore
    assert "!examples/codex-maintenance/trace-order-b.jsonl" in gitignore
    assert "global-exclude *.jsonl" in manifest
    assert "global-exclude *.pem" in manifest
    assert "global-exclude *.key" in manifest
    assert "include examples/codex-maintenance/trace-order-a.jsonl" in manifest
    assert "include examples/codex-maintenance/trace-order-b.jsonl" in manifest
