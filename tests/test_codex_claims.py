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


def test_no_source_changes_stays_unverified_without_git_evidence() -> None:
    claims, _ = verify_claims(
        [{"id": "clean", "type": "no-source-changes", "evidence_ids": ["git-end"]}],
        {"commands": [], "evidence_ids": []},
    )

    assert claims[0].status == "unverified"
    assert "unavailable" in claims[0].reason.lower()


def test_files_changed_can_use_available_trace_evidence_without_git() -> None:
    claims, _ = verify_claims(
        [{"id": "files", "type": "files-changed", "expected_files": ["src/bug.py"]}],
        {
            "commands": [],
            "trace_files": [{"path": "src/bug.py"}],
            "evidence_ids": ["trace-files"],
        },
    )

    assert claims[0].evidence_ids == ["trace-files"]
    assert claims[0].status == "supported"


def test_command_claim_is_unverified_when_any_cited_command_is_incomplete() -> None:
    claims, _ = verify_claims(
        [
            {
                "id": "tests",
                "type": "tests-passed",
                "evidence_ids": ["complete", "timed-out"],
            }
        ],
        {
            "commands": [
                {
                    "id": "complete",
                    "display_command": "pytest tests/complete.py",
                    "exit_code": 0,
                    "timed_out": False,
                },
                {
                    "id": "timed-out",
                    "display_command": "pytest tests/slow.py",
                    "exit_code": None,
                    "timed_out": True,
                },
            ],
            "evidence_ids": ["complete", "timed-out"],
        },
    )

    assert claims[0].status == "unverified"
    assert "incomplete" in claims[0].reason.lower()


def test_claim_types_require_semantically_matching_evidence_ids() -> None:
    claims, _ = verify_claims(
        [
            {"id": "bug", "type": "bug-reproduced", "evidence_ids": ["trace"]},
            {"id": "fix", "type": "fix-verified", "evidence_ids": ["trace"]},
        ],
        {
            "commands": [],
            "baseline": {"outcome": "reproduced"},
            "verification": {"outcome": "verified"},
            "evidence_ids": ["trace", "baseline-reproduction", "verification"],
        },
    )

    assert all(claim.status == "unverified" for claim in claims)
    assert all("required evidence" in claim.reason.lower() for claim in claims)


def test_command_auto_matching_does_not_treat_substrings_as_test_runners() -> None:
    claims, _ = verify_claims(
        [{"id": "tests", "type": "tests-passed"}],
        {
            "commands": [
                {
                    "id": "version",
                    "argv": ["contest.exe", "--version"],
                    "display_command": "contest.exe --version",
                    "exit_code": 0,
                    "timed_out": False,
                }
            ],
            "evidence_ids": ["version"],
        },
    )

    assert claims[0].evidence_ids == []
    assert claims[0].status == "unverified"


def test_no_source_changes_cannot_ignore_conflicting_trace_file_evidence() -> None:
    evidence = {
        "commands": [],
        "git": {
            "end": {
                "changed_files": [],
                "captured": True,
                "changed_files_truncated": False,
            }
        },
        "trace_files": [{"path": "src/bug.py"}],
        "evidence_ids": ["git-end", "trace-files"],
    }

    uncited, _ = verify_claims(
        [{"id": "clean", "type": "no-source-changes", "evidence_ids": ["git-end"]}],
        evidence,
    )
    cited, _ = verify_claims(
        [
            {
                "id": "clean",
                "type": "no-source-changes",
                "evidence_ids": ["git-end", "trace-files"],
            }
        ],
        evidence,
    )

    assert uncited[0].status == "unverified"
    assert cited[0].status == "refuted"


def test_files_changed_rejects_paths_outside_repository_scope() -> None:
    claims, _ = verify_claims(
        [
            {
                "id": "files",
                "type": "files-changed",
                "expected_files": ["../../outside.py"],
                "evidence_ids": ["trace-files"],
            }
        ],
        {
            "commands": [],
            "trace_files": [{"path": "../../outside.py"}],
            "evidence_ids": ["trace-files"],
        },
    )

    assert claims[0].status == "unverified"
    assert "repository-relative" in claims[0].reason
