from uuid import uuid4

from taskiller.auth.security import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
    normalize_email,
    password_hasher,
)
from taskiller.core.config import Settings


def settings(
    *,
    jwt_secret: str = "change-me-in-local-development",
    token_hash_secret: str = "change-me-in-local-development-token-hash",
) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=jwt_secret,
        token_hash_secret=token_hash_secret,
    )


def test_passwords_use_one_way_hashes() -> None:
    encoded = password_hasher.hash("long-enough-secret")

    assert encoded != "long-enough-secret"
    assert password_hasher.verify("long-enough-secret", encoded)
    assert not password_hasher.verify("wrong-secret", encoded)


def test_access_token_binds_user_and_session() -> None:
    cfg = settings(jwt_secret="x" * 64)
    user_id = uuid4()
    session_id = uuid4()

    encoded, expires = create_access_token(user_id, session_id, cfg)
    decoded = decode_access_token(encoded, cfg)

    assert decoded is not None
    assert decoded.user_id == user_id
    assert decoded.session_id == session_id
    assert decoded.expires_at == expires


def test_access_token_rejects_wrong_signing_key() -> None:
    cfg = settings(jwt_secret="x" * 64)
    other = settings(jwt_secret="y" * 64)
    encoded, _ = create_access_token(uuid4(), uuid4(), cfg)

    assert decode_access_token(encoded, other) is None


def test_opaque_token_hash_is_keyed_and_plaintext_is_not_hash() -> None:
    token = generate_opaque_token()
    one = hash_opaque_token(token, settings(token_hash_secret="a" * 64))
    two = hash_opaque_token(token, settings(token_hash_secret="b" * 64))

    assert token not in {one, two}
    assert one != two
    assert len(one) == 64


def test_email_normalization_is_stable() -> None:
    assert normalize_email("  Person@Example.COM ") == "person@example.com"
