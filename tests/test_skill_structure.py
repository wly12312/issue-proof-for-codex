import json
import re
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
    ui = (skill.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "display_name:" in ui and "short_description:" in ui and "$reproduce-github-issue" in ui
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "oss-issue-proof"
    assert manifest["skills"] == "./skills/"
    assert re.fullmatch(r"[a-z0-9-]+", manifest["name"])
