import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


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
    executable = shutil.which("issue-proof", path=environment["PATH"])
    assert executable, "the installed CLI is required for the standalone delegate test"
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
    assert result.stdout.strip() == "0.1.0"
    script = (standalone_skill / "scripts" / "run_issue_proof.py").read_text(encoding="utf-8")
    assert "sys.path" not in script
    assert ".parents" not in script
