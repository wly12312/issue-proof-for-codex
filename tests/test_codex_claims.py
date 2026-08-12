from issue_proof.codex.claims import load_claim_inputs, verify_claims


def _evidence() -> dict:
    return {
        "commands": [
            {"id": "tests", "display_command": "pytest -q", "exit_code": 0, "timed_out": False},
            {"id": "lint", "display_command": "ruff check .", "exit_code": 1, "timed_out": False},
        ],
        "baseline": {"outcome": "reproduced"},
        "verification": {"outcome": "verified"},
        "git": {"end": {"changed_files": ["src/bug.py"]}},
        "trace_files": [{"path": "src/bug.py"}],
        "evidence_ids": [
            "tests",
            "lint",
            "baseline-reproduction",
            "verification",
            "git-end",
            "trace-files",
        ],
    }


def test_claims_distinguish_supported_refuted_and_missing_evidence() -> None:
    claims, warnings = verify_claims(
        [
            {"id": "tests", "type": "tests-passed", "evidence_ids": ["tests"]},
            {"id": "lint", "type": "lint-passed", "evidence_ids": ["lint"]},
            {"id": "fix", "type": "fix-verified", "evidence_ids": ["verification"]},
            {"id": "missing", "type": "build-passed", "evidence_ids": ["does-not-exist"]},
            {"id": "conflict", "type": "tests-passed", "evidence_ids": ["tests", "lint"]},
            {
                "id": "files",
                "type": "files-changed",
                "expected_files": ["src/bug.py"],
                "evidence_ids": ["git-end"],
            },
        ],
        _evidence(),
    )
    by_id = {claim.id: claim for claim in claims}
    assert by_id["tests"].status == "supported"
    assert by_id["lint"].status == "refuted"
    assert by_id["fix"].status == "supported"
    assert by_id["missing"].status == "unverified"
    assert by_id["conflict"].status == "unverified"
    assert by_id["files"].status == "supported"
    assert warnings == []


def test_claims_yaml_loader_supports_small_explicit_shape(tmp_path) -> None:
    path = tmp_path / "claims.yaml"
    path.write_text(
        "claims:\n  - id: smoke\n    type: tests-passed\n    evidence_ids: [tests]\n",
        encoding="utf-8",
    )
    loaded = load_claim_inputs(path)
    assert loaded[0]["id"] == "smoke"
    assert loaded[0]["evidence_ids"] == ["tests"]


def test_claims_are_not_inferred_from_untrusted_message_without_opt_in() -> None:
    evidence = _evidence() | {"final_messages": [{"text": "tests passed"}]}
    claims, warnings = verify_claims([], evidence)
    assert claims == []
    assert warnings == []
    claims, warnings = verify_claims([], evidence, include_heuristics=True)
    assert claims[0].heuristic is True
    assert claims[0].source == "final-message-heuristic"
    assert "heuristic" in warnings[0]


def test_changed_file_claims_stay_unverified_when_git_list_is_truncated() -> None:
    evidence = _evidence() | {
        "git": {
            "end": {
                "changed_files": [],
                "captured": True,
                "changed_files_truncated": True,
                "changed_files_overflow": True,
            }
        }
    }
    claims, _ = verify_claims(
        [
            {
                "id": "files",
                "type": "files-changed",
                "expected_files": ["src/bug.py"],
                "evidence_ids": ["git-end"],
            },
            {"id": "clean", "type": "no-source-changes", "evidence_ids": ["git-end"]},
        ],
        evidence,
    )
    by_id = {claim.id: claim for claim in claims}
    assert by_id["files"].status == "unverified"
    assert by_id["clean"].status == "unverified"
