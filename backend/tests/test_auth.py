"""Auth tests — xác thực server-side, chống giả mạo danh tính."""

import asyncio
import base64
import json
import time
import uuid

import pytest

pytestmark = pytest.mark.asyncio


def b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def make_expired_token(user_id: str) -> str:
    """Tự ký token hết hạn bằng secret của settings test (xung đột nào cũng bắt được)."""
    import jwt

    from app.core.config import get_settings

    s = get_settings()
    now = int(time.time()) - 3600
    payload = {
        "sub": user_id,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": now,
        "exp": now - 10,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


async def register(client, email=None, password="Passw0rd!123"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    return email, password, r.cookies


def csrf_headers(client) -> dict:
    """Header X-CSRF-Token lấy từ csrf cookie trong jar (double-submit)."""
    token = client.cookies.get("csrf_token") or ""
    return {"X-CSRF-Token": token}


async def login(client, email, password):
    return await client.post("/v1/auth/login", json={"email": email, "password": password})


async def create_course(client, topic="Python auth flow"):
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    return r


async def test_unauthenticated_request_returns_401(client):
    r = await client.get("/v1/courses/crs_00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "NOT_AUTHENTICATED"

    rc = await create_course(client)
    assert rc.status_code == 401


async def test_register_login_me_flow(client):
    email, password, _ = await register(client)
    rl = await login(client, email, password)
    assert rl.status_code == 200, rl.text
    assert rl.json()["email"] == email

    rm = await client.get("/v1/auth/me")
    assert rm.status_code == 200
    assert rm.json()["email"] == email

    # Password không được lưu plaintext
    from sqlalchemy import select

    from app.models import User

    result = await client.app_state if False else None  # placeholder tránh linter
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        assert u.password_hash is not None
        assert password not in u.password_hash
        assert u.password_hash.startswith("$argon2id$")


async def test_register_duplicate_email_409(client):
    email, _, _ = await register(client)
    r = await client.post("/v1/auth/register", json={"email": email, "password": "Passw0rd!123"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EMAIL_TAKEN"


async def test_wrong_password_401(client):
    email, _, _ = await register(client)
    r = await login(client, email, "SaiMatKhau!999")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_weak_password_rejected(client):
    r = await client.post("/v1/auth/register", json={"email": f"weak-{uuid.uuid4().hex[:6]}@t.dev", "password": "short"})
    assert r.status_code == 422


async def test_expired_token_rejected(client):
    from app.db.session import SessionLocal
    from app.models import User
    from sqlalchemy import select

    email, password, _ = await register(client)
    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user_id = str(u.id)

    expired = make_expired_token(user_id)
    r = await client.get(
        "/v1/auth/me",
        cookies={"access_token": expired, "csrf_token": "x"},
        headers={"X-CSRF-Token": "x"},
    )
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_tampered_token_rejected(client):
    r = await client.get(
        "/v1/auth/me",
        cookies={"access_token": "eyJhbGciOiJIUzI1NiJ9.tampered.forged", "csrf_token": "x"},
        headers={"X-CSRF-Token": "x"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] in ("TOKEN_INVALID", "TOKEN_EXPIRED")


async def test_wrong_issuer_or_audience_rejected(client):
    import jwt as pyjwt

    from app.core.config import get_settings

    s = get_settings()
    now = int(time.time())
    for payload in (
        {"sub": uuid.uuid4().hex, "iss": "attacker", "aud": s.jwt_audience, "iat": now, "exp": now + 600},
        {"sub": uuid.uuid4().hex, "iss": s.jwt_issuer, "aud": "other-aud", "iat": now, "exp": now + 600},
    ):
        token = pyjwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
        r = await client.get(
            "/v1/auth/me",
            cookies={"access_token": token, "csrf_token": "x"},
            headers={"X-CSRF-Token": "x"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOKEN_INVALID"


async def test_fake_x_user_id_header_does_not_authenticate(client):
    """Header X-User-Id giả mạo không vượt qua được auth khi demo mode tắt."""
    r = await client.get("/v1/courses/crs_00000000-0000-0000-0000-000000000000", headers={"X-User-Id": "admin"})
    assert r.status_code == 401

    r2 = await client.post(
        "/v1/courses",
        json={"topic": "t", "clientCourseId": uuid.uuid4().hex[:16]},
        headers={"X-User-Id": "e2e-user-abc", "X-CSRF-Token": "x"},
        cookies={"csrf_token": "x"},
    )
    assert r2.status_code == 401


async def test_csrf_missing_on_mutation_403(client):
    await register(client)
    # GET không cần CSRF
    rm = await client.get("/v1/auth/me")
    assert rm.status_code == 200
    # POST thiếu X-CSRF-Token → 403
    r = await client.post(
        "/v1/courses",
        json={"topic": "t", "clientCourseId": uuid.uuid4().hex[:16]},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "CSRF_INVALID"
    # POST có X-CSRF-Token khớp cookie → pass
    r2 = await client.post(
        "/v1/courses",
        json={"topic": "t", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r2.status_code == 201


async def test_cross_user_access_denied(client):
    # User A đăng ký + tạo course + trả lời interview + approve
    email_a = f"a-{uuid.uuid4().hex[:8]}@test.dev"
    await client.post("/v1/auth/register", json={"email": email_a, "password": "Passw0rd!123"})
    ra = await client.post(
        "/v1/courses",
        json={"topic": "Course cua A", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert ra.status_code == 201
    course_id = ra.json()["id"]
    for i in range(5):
        await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"answer {i}"},
            headers=csrf_headers(client),
        )
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    for _ in range(100):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    rcd = await client.get(f"/v1/courses/{course_id}")
    lesson_id = rcd.json()["units"][0]["lessons"][0]["id"]

    # User B đăng ký (cookie replaced) → truy cập tài nguyên A
    email_b = f"b-{uuid.uuid4().hex[:8]}@test.dev"
    await client.post("/v1/auth/register", json={"email": email_b, "password": "Passw0rd!123"})

    r1 = await client.get(f"/v1/courses/{course_id}")
    assert r1.status_code == 404
    r2 = await client.get(f"/v1/courses/{course_id}/generation")
    assert r2.status_code == 404
    r3 = await client.get(f"/v1/lessons/{lesson_id}")
    assert r3.status_code == 404

    # A đăng nhập lại vẫn truy cập được course của mình
    await login(client, email_a, "Passw0rd!123")
    r4 = await client.get(f"/v1/courses/{course_id}")
    assert r4.status_code == 200


async def test_login_reload_and_continue(client):
    """Đăng nhập → tạo course + học → 'reload' (client mới, cùng cookie jar) → dữ liệu còn."""
    email = f"persist-{uuid.uuid4().hex[:8]}@test.dev"
    await client.post("/v1/auth/register", json={"email": email, "password": "Passw0rd!123"})
    rc = await create_course(client, "Persistence check")
    course_id = rc.json()["id"]
    for i in range(5):
        await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"ans {i}"},
            headers=csrf_headers(client),
        )
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    for _ in range(100):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break

    rcd = await client.get(f"/v1/courses/{course_id}")
    lesson_id = rcd.json()["units"][0]["lessons"][0]["id"]
    rl = await client.get(f"/v1/lessons/{lesson_id}")
    lesson = rl.json()

    ra = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": uuid.uuid4().hex[:16],
            "contentVersion": lesson["contentVersion"],
            "answers": [
                {"index": idx, "answer": b.get("answerIndex") if b["type"] == "mc" else "x"}
                for idx, b in enumerate(lesson["blocks"])
                if b["type"] != "teach"
            ],
        },
        headers=csrf_headers(client),
    )
    assert ra.status_code == 201

    # "Reload": GET lại với session cookie (httpx giữ cookie jar) + /me xác nhận phiên còn
    rm = await client.get("/v1/auth/me")
    assert rm.status_code == 200
    assert rm.json()["email"] == email
    rcd2 = await client.get(f"/v1/courses/{course_id}")
    assert rcd2.status_code == 200
    assert rcd2.json()["units"][0]["lessons"][0]["id"] == lesson_id


async def test_logout_clears_session(client):
    email, _, _ = await register(client)
    assert (await client.get("/v1/auth/me")).status_code == 200
    lo = await client.post("/v1/auth/logout", headers=csrf_headers(client))
    assert lo.status_code == 204
    rm = await client.get("/v1/auth/me")
    assert rm.status_code == 401


# ---------- P0.5.1 regression ----------


async def test_invalid_email_returns_422_not_401(client):
    """Bug fix: INVALID_EMAIL phải là 422 (UNPROCESSABLE_ENTITY), không phải hằng số sai."""
    r = await client.post(
        "/v1/auth/register",
        json={"email": "khong-phai-email", "password": "Passw0rd!123"},
    )
    assert r.status_code == 422, r.text
    # 422 chuẩn không được kèm WWW-Authenticate (đó là hành vi 401)
    assert "www-authenticate" not in {k.lower() for k in r.headers}


async def test_weak_password_returns_422_with_code(client):
    # Password ngắn bị Pydantic schema chặn trước (422 list) — validate_password chỉ là lớp phòng
    # thứ 2 với cùng điều kiện. Kiểm tra cả 2 tầng:
    r = await client.post(
        "/v1/auth/register",
        json={"email": f"weak-{uuid.uuid4().hex[:6]}@t.dev", "password": "ngan"},
    )
    assert r.status_code == 422  # schema-level

    # service-level: gọi trực tiếp validate_password
    from fastapi import HTTPException

    from app.services.user_service import validate_password

    with pytest.raises(HTTPException) as exc:
        validate_password("ngan")
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WEAK_PASSWORD"


async def test_login_rate_limited(client):
    """Rate limit đăng nhập: vượt ngưỡng → 429."""
    from app.core.limits import clear_rate_limits

    clear_rate_limits()
    email = f"rl-{uuid.uuid4().hex[:6]}@test.dev"
    try:
        for i in range(10):
            r = await client.post(
                "/v1/auth/login",
                json={"email": email, "password": f"wrong-attempt-{i}!"},
            )
            # 10 lần đầu không bị chặn (401 do sai mật khẩu)
            assert r.status_code == 401, f"attempt {i}: {r.status_code}"
        # Lần 11 → 429
        r11 = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": "wrong-again!"},
        )
        assert r11.status_code == 429, r11.text
        assert r11.json()["detail"]["code"] == "RATE_LIMITED"
    finally:
        clear_rate_limits()


async def test_register_rate_limited(client):
    from app.core.limits import clear_rate_limits

    clear_rate_limits()
    try:
        for i in range(10):
            r = await client.post(
                "/v1/auth/register",
                json={"email": f"rl-reg-{uuid.uuid4().hex[:6]}@t.dev", "password": "Passw0rd!123"},
            )
            assert r.status_code == 201, f"attempt {i}: {r.status_code}"
        r11 = await client.post(
            "/v1/auth/register",
            json={"email": f"rl-reg-{uuid.uuid4().hex[:6]}@t.dev", "password": "Passw0rd!123"},
        )
        assert r11.status_code == 429, r11.text
    finally:
        clear_rate_limits()


async def test_valid_token_with_deleted_user_returns_401(client):
    """Token còn hợp lệ nhưng user đã bị xóa khỏi DB → 401 (không crash)."""
    from sqlalchemy import delete, select

    from app.db.session import SessionLocal
    from app.models import User

    email = f"del-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": "Passw0rd!123"})
    assert r.status_code == 201
    # session cookie đang hợp lệ — xác nhận /me OK trước khi xóa
    assert (await client.get("/v1/auth/me")).status_code == 200

    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        await db.execute(delete(User).where(User.id == u.id))
        await db.commit()

    rm = await client.get("/v1/auth/me")
    assert rm.status_code == 401
    assert rm.json()["detail"]["code"] == "USER_NOT_FOUND"


async def test_rate_limit_buckets_reset_between_tests(client):
    """Fixture client phải clear buckets — test này chạy ngay sau test rate limit mà không bị 429."""
    r = await client.post(
        "/v1/auth/login",
        json={"email": "fresh-after-rl@test.dev", "password": "whatever1"},
    )
    assert r.status_code == 401  # 401 (sai credentials), KHÔNG phải 429


async def test_me_after_login_same_user_no_crossuser_leak(client):
    """Auth resolution trong cùng request scope: /me trả đúng user đang đăng nhập."""
    email_a = f"scope-a-{uuid.uuid4().hex[:6]}@test.dev"
    await client.post("/v1/auth/register", json={"email": email_a, "password": "Passw0rd!123"})
    me_a = (await client.get("/v1/auth/me")).json()

    email_b = f"scope-b-{uuid.uuid4().hex[:6]}@test.dev"
    await client.post("/v1/auth/register", json={"email": email_b, "password": "Passw0rd!123"})
    me_b = (await client.get("/v1/auth/me")).json()

    assert me_a["id"] != me_b["id"]
    assert me_b["email"] == email_b
