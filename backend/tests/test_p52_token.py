"""P5.2 token — ký/verify, hết hạn, sai user/course, canonical hash."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services import recommendation_token_service as tok


def _mint(**over):
    base = dict(
        user_id=str(uuid.uuid4()),
        course_id=str(uuid.uuid4()),
        arm_kind="next_lesson",
        arm_id=str(uuid.uuid4()),
        context_hash="a" * 64,
        lesson_content_version=1,
        policy_version="p5.0-rule-v1",
    )
    base.update(over)
    return base


def test_mint_then_verify_roundtrip():
    args = _mint()
    token = tok.mint(**args)
    payload = tok.verify(token, user_id=args["user_id"], course_id=args["course_id"])
    assert payload["armKind"] == args["arm_kind"]
    assert payload["armId"] == args["arm_id"]
    assert payload["lessonContentVersion"] == 1
    assert payload["contextHash"] == "a" * 64


def test_verify_rejects_other_user():
    args = _mint()
    token = tok.mint(**args)
    with pytest.raises(tok.TokenError) as exc:
        tok.verify(token, user_id=str(uuid.uuid4()), course_id=args["course_id"])
    assert exc.value.reason == "TOKEN_INVALID"


def test_verify_rejects_other_course():
    args = _mint()
    token = tok.mint(**args)
    with pytest.raises(tok.TokenError):
        tok.verify(token, user_id=args["user_id"], course_id=str(uuid.uuid4()))


def test_verify_rejects_tampered_token():
    args = _mint()
    token = tok.mint(**args)
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(tok.TokenError):
        tok.verify(tampered, user_id=args["user_id"], course_id=args["course_id"])


def test_verify_rejects_expired():
    args = _mint()
    issued = datetime(2026, 1, 1, tzinfo=UTC)
    token = tok.mint(**args, now=issued)
    with pytest.raises(tok.TokenError) as exc:
        tok.verify(
            token,
            user_id=args["user_id"],
            course_id=args["course_id"],
            now=issued + timedelta(hours=2),
        )
    assert exc.value.reason == "TOKEN_EXPIRED"


def test_context_hash_is_order_independent():
    path_a = {
        "nextLesson": {"lessonId": "lsn_a", "title": "A", "reason": {"code": "X"}},
        "reviewLessonId": None,
        "reviewDueCount": 2,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [{"id": "s1"}], "edges": []},
    }
    path_b = {
        "prerequisitesDag": {"edges": [], "nodes": [{"id": "s1"}]},
        "blockedBy": [],
        "reviewDueCount": 2,
        "reviewLessonId": None,
        "nextLesson": {"reason": {"code": "X"}, "title": "A", "lessonId": "lsn_a"},
    }
    assert tok.context_hash_from_path(path_a) == tok.context_hash_from_path(path_b)
    assert len(tok.context_hash_from_path(path_a)) == 64


def test_context_hash_changes_with_arm():
    base = {
        "nextLesson": {"lessonId": "lsn_a"},
        "reviewLessonId": None,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }
    other = {**base, "nextLesson": {"lessonId": "lsn_b"}}
    assert tok.context_hash_from_path(base) != tok.context_hash_from_path(other)


def test_context_hash_ignores_titles_and_messages():
    """Đổi wording/nội dung hiển thị không được làm token cũ thành stale."""
    a = {
        "nextLesson": {"lessonId": "lsn_a", "title": "Cũ", "reason": {"code": "X", "message": "m1"}},
        "reviewLessonId": None,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }
    b = {
        "nextLesson": {"lessonId": "lsn_a", "title": "Mới", "reason": {"code": "X", "message": "m2"}},
        "reviewLessonId": None,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }
    assert tok.context_hash_from_path(a) == tok.context_hash_from_path(b)


def test_mint_requires_secret(monkeypatch):
    monkeypatch.setattr(tok, "_secret", lambda: "")
    with pytest.raises(RuntimeError):
        tok.mint(**_mint())


# ---- Final review fixes -------------------------------------------------


def test_verify_rejects_non_ascii_signature_without_crashing():
    """`hmac.compare_digest` trên str non-ASCII ném TypeError ⇒ phải thành TokenError."""
    args = _mint()
    token = tok.mint(**args)
    payload_part, _sig = token.split(".", 1)
    with pytest.raises(tok.TokenError):
        tok.verify(
            f"{payload_part}.chữ_ký_giả",
            user_id=args["user_id"],
            course_id=args["course_id"],
        )


def test_verify_rejects_garbage_without_crashing():
    args = _mint()
    for bad in ("", ".", "....", "not-base64!!.also-bad!!", "a.b"):
        with pytest.raises(tok.TokenError):
            tok.verify(bad, user_id=args["user_id"], course_id=args["course_id"])


def test_verify_exposes_policy_version():
    args = _mint(policy_version="p5.0-rule-v1")
    token = tok.mint(**args)
    payload = tok.verify(token, user_id=args["user_id"], course_id=args["course_id"])
    assert payload["policyVersion"] == "p5.0-rule-v1"
