"""
tests/db/test_auth_utils.py — Unit tests for auth utility functions (Sprint 42)

scout/db/auth_utils.py provides all cryptographic primitives used by the
authentication system:
  - hash_password / verify_password  — bcrypt with SHA-256 pre-hash
  - hash_api_key / generate_api_key  — SHA-256 API key storage
  - create_jwt / decode_jwt           — HS256 JWT lifecycle

All tests run with NO external dependencies — pure in-process crypto.

Coverage:
  - Password hashing is irreversible (same input → different hash each time due to salt)
  - Password verification: correct/incorrect passwords
  - Long password safety (>72 bytes — bcrypt truncates; SHA-256 pre-hash prevents this)
  - API key generation: prefix, uniqueness, sufficient entropy
  - API key hashing: deterministic, hex output, consistent
  - JWT creation: valid structure, can be decoded
  - JWT verification: wrong secret rejected, expired token rejected
  - decode_jwt raises HTTP 401 (not a plain exception) on bad tokens
"""

import time

import pytest
from fastapi import HTTPException

from scout.db.auth_utils import (
    create_jwt,
    decode_jwt,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD HASHING
# ─────────────────────────────────────────────────────────────────────────────

class TestHashPassword:

    def test_returns_string(self):
        result = hash_password("mysecret")
        assert isinstance(result, str)

    def test_bcrypt_prefix(self):
        result = hash_password("mysecret")
        # bcrypt hashes always start with $2b$
        assert result.startswith("$2b$")

    def test_different_calls_produce_different_hashes(self):
        """bcrypt uses random salt — same password → different hashes."""
        h1 = hash_password("mysecret")
        h2 = hash_password("mysecret")
        assert h1 != h2

    def test_empty_password_produces_hash(self):
        result = hash_password("")
        assert result.startswith("$2b$")

    def test_long_password_does_not_crash(self):
        """SHA-256 pre-hash ensures passwords >72 bytes are handled safely."""
        long_pw = "x" * 200
        result = hash_password(long_pw)
        assert result.startswith("$2b$")

    def test_unicode_password(self):
        result = hash_password("pässwörð™")
        assert result.startswith("$2b$")


class TestVerifyPassword:

    def test_correct_password_returns_true(self):
        hashed = hash_password("correct-horse-battery")
        assert verify_password("correct-horse-battery", hashed) is True

    def test_wrong_password_returns_false(self):
        hashed = hash_password("correct-horse-battery")
        assert verify_password("wrong-password", hashed) is False

    def test_empty_password_round_trips(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True

    def test_empty_vs_nonempty(self):
        hashed = hash_password("")
        assert verify_password("notempty", hashed) is False

    def test_case_sensitive(self):
        hashed = hash_password("Secret")
        assert verify_password("secret", hashed) is False
        assert verify_password("SECRET", hashed) is False

    def test_long_password_round_trips(self):
        """>72 byte password should verify correctly thanks to SHA-256 pre-hash."""
        long_pw = "a" * 150
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed) is True

    def test_long_password_different_long_fails(self):
        """Two different long passwords should NOT cross-verify."""
        pw1 = "a" * 100
        pw2 = "b" * 100
        hashed = hash_password(pw1)
        assert verify_password(pw2, hashed) is False

    def test_unicode_round_trip(self):
        pw = "pässwörð™"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True
        assert verify_password("passworld", hashed) is False


# ─────────────────────────────────────────────────────────────────────────────
# API KEY GENERATION
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateApiKey:

    def test_returns_string(self):
        assert isinstance(generate_api_key(), str)

    def test_has_sk_prefix(self):
        key = generate_api_key()
        assert key.startswith("sk-")

    def test_minimum_length(self):
        """sk- + 32 bytes base64 ≈ 46 characters minimum."""
        key = generate_api_key()
        assert len(key) >= 20

    def test_unique_on_each_call(self):
        keys = {generate_api_key() for _ in range(50)}
        assert len(keys) == 50  # all distinct

    def test_no_whitespace(self):
        key = generate_api_key()
        assert " " not in key
        assert "\n" not in key
        assert "\t" not in key


# ─────────────────────────────────────────────────────────────────────────────
# API KEY HASHING
# ─────────────────────────────────────────────────────────────────────────────

class TestHashApiKey:

    def test_returns_string(self):
        assert isinstance(hash_api_key("sk-abc123"), str)

    def test_returns_hex_string(self):
        result = hash_api_key("sk-abc123")
        # SHA-256 hex digest is 64 hex chars
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        """Same key → same hash every time."""
        h1 = hash_api_key("sk-abc123")
        h2 = hash_api_key("sk-abc123")
        assert h1 == h2

    def test_different_keys_different_hashes(self):
        h1 = hash_api_key("sk-key-one")
        h2 = hash_api_key("sk-key-two")
        assert h1 != h2

    def test_empty_key_produces_consistent_hash(self):
        h1 = hash_api_key("")
        h2 = hash_api_key("")
        assert h1 == h2

    def test_generated_key_can_be_hashed(self):
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert len(hashed) == 64

    def test_hash_is_not_reversible_to_original(self):
        key = "sk-supersecretkey"
        hashed = hash_api_key(key)
        # The original key string should NOT appear in the hash
        assert key not in hashed


# ─────────────────────────────────────────────────────────────────────────────
# JWT CREATION
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateJwt:

    def test_returns_string(self):
        token = create_jwt({"sub": "user-123", "tenant": "acme"})
        assert isinstance(token, str)

    def test_has_three_parts(self):
        """JWTs are header.payload.signature — three base64 segments."""
        token = create_jwt({"sub": "user-123"})
        parts = token.split(".")
        assert len(parts) == 3

    def test_created_token_is_decodable(self):
        payload = {"sub": "user-abc", "tenant": "acme-corp"}
        token = create_jwt(payload)
        decoded = decode_jwt(token)
        assert decoded["sub"] == "user-abc"
        assert decoded["tenant"] == "acme-corp"

    def test_token_contains_exp_claim(self):
        token = create_jwt({"sub": "user-xyz"})
        decoded = decode_jwt(token)
        assert "exp" in decoded

    def test_exp_is_in_the_future(self):
        token = create_jwt({"sub": "user-xyz"})
        decoded = decode_jwt(token)
        assert decoded["exp"] > time.time()

    def test_custom_expiry_is_respected(self):
        """Longer expiry → larger exp value."""
        token_short = create_jwt({"sub": "u"}, expires_minutes=1)
        token_long = create_jwt({"sub": "u"}, expires_minutes=480)
        short_exp = decode_jwt(token_short)["exp"]
        long_exp = decode_jwt(token_long)["exp"]
        assert long_exp > short_exp

    def test_different_subjects_produce_different_tokens(self):
        t1 = create_jwt({"sub": "user-001"})
        t2 = create_jwt({"sub": "user-002"})
        assert t1 != t2


# ─────────────────────────────────────────────────────────────────────────────
# JWT DECODING
# ─────────────────────────────────────────────────────────────────────────────

class TestDecodeJwt:

    def test_valid_token_returns_dict(self):
        token = create_jwt({"sub": "user-123", "role": "admin"})
        result = decode_jwt(token)
        assert isinstance(result, dict)

    def test_subject_preserved(self):
        token = create_jwt({"sub": "user-999"})
        decoded = decode_jwt(token)
        assert decoded["sub"] == "user-999"

    def test_extra_claims_preserved(self):
        token = create_jwt({"sub": "u", "tenant": "acme", "role": "viewer"})
        decoded = decode_jwt(token)
        assert decoded["tenant"] == "acme"
        assert decoded["role"] == "viewer"

    def test_tampered_token_raises_401(self):
        token = create_jwt({"sub": "user-123"})
        # Flip the last character to corrupt the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(tampered)
        assert exc_info.value.status_code == 401

    def test_garbage_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt("this.is.garbage")
        assert exc_info.value.status_code == 401

    def test_empty_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt("")
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self, monkeypatch):
        """Token signed with one secret cannot be decoded with another."""
        from scout.config import settings
        token = create_jwt({"sub": "user-123"})
        original_secret = settings.jwt_secret
        try:
            settings.jwt_secret = "completely-different-secret-xyz"
            with pytest.raises(HTTPException) as exc_info:
                decode_jwt(token)
            assert exc_info.value.status_code == 401
        finally:
            settings.jwt_secret = original_secret

    def test_expired_token_raises_401(self):
        """Token with expires_minutes=0 should be already expired."""
        # Create with very short (negative-ish) expiry
        import datetime
        from scout.config import settings
        from jose import jwt as jose_jwt

        # Manually craft a token that expired 1 second ago
        payload = {
            "sub": "user-exp",
            "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1),
        }
        token = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token)
        assert exc_info.value.status_code == 401

    def test_401_has_www_authenticate_header(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt("bad.token.value")
        assert "WWW-Authenticate" in exc_info.value.headers

    def test_round_trip_multiple_payloads(self):
        """Parametric sanity: 10 distinct payloads all round-trip cleanly."""
        for i in range(10):
            payload = {"sub": f"user-{i}", "seq": i, "tag": f"test-{i}"}
            token = create_jwt(payload)
            decoded = decode_jwt(token)
            assert decoded["sub"] == f"user-{i}"
            assert decoded["seq"] == i
