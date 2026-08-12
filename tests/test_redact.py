from issue_proof.redact import decode_and_redact, redact_text, sha256_text


def test_redacts_common_credentials_and_private_key() -> None:
    result = redact_text(
        "ghp_1234567890abcdef https://alice:password@example.test/x "
        "Authorization: Bearer abc.def.ghi token=super-secret "
        "AKIA1234567890ABCDEF sk-proj-1234567890abcdef "
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    )
    assert result.redacted is True
    assert "[REDACTED]" in result.text
    assert "password@example" not in result.text
    assert "super-secret" not in result.text
    assert "BEGIN PRIVATE KEY" not in result.text


def test_decode_replaces_invalid_utf8_before_redaction() -> None:
    result = decode_and_redact(b"prefix\xff token=secret")
    assert "\ufffd" in result.text
    assert "secret" not in result.text


def test_sha256_is_stable() -> None:
    assert sha256_text("same") == sha256_text("same")
    assert len(sha256_text("same")) == 64
