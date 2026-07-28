"""
Tests for scripts/usage.py — currently just _read_token()'s error paths.

Focused on the macOS-Keychain diagnostic added alongside this test: a
missing credentials file previously raised a bare FileNotFoundError with no
hint about why (Claude Code may store the OAuth token in the system
Keychain instead of writing this file at all); it now raises a RuntimeError
that says so.
"""

import json
import os

import pytest

import usage


def test_read_token_missing_file_hints_at_keychain(tmp_path, monkeypatch):
    missing = os.path.join(str(tmp_path), "does-not-exist.json")
    monkeypatch.setattr(usage, "CREDENTIALS_FILE", missing)
    with pytest.raises(RuntimeError, match="Keychain"):
        usage._read_token()


def test_read_token_missing_access_token_still_hints_at_keychain(tmp_path, monkeypatch):
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps({"claudeAiOauth": {}}), encoding="utf-8")
    monkeypatch.setattr(usage, "CREDENTIALS_FILE", str(creds_file))
    with pytest.raises(RuntimeError, match="keychain"):
        usage._read_token()


def test_read_token_returns_token_when_present(tmp_path, monkeypatch):
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-test-123"}}), encoding="utf-8"
    )
    monkeypatch.setattr(usage, "CREDENTIALS_FILE", str(creds_file))
    assert usage._read_token() == "sk-test-123"
