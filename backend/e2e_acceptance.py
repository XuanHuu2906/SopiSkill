"""E2E acceptance verification — chạy thật qua HTTP với uvicorn server đang chạy.

Kịch bản theo Acceptance Criteria:
0. Đăng ký + đăng nhập hợp lệ (cookie auth) — bắt buộc trước mọi API call
1. Nhập chủ đề "Python cho người mới"
2. Trả lời 5 câu phỏng vấn
3. Nhận proposal có cấu trúc hợp lệ
4. Duyệt proposal
5. Theo dõi job generation
6. Nhận >= 2 bài học
7. Mở và học một bài
8. Làm quiz và lưu kết quả
9. Tải lại trang mà không mất dữ liệu (GET lại lesson + attempts tồn tại)
+ Case lỗi: unauthenticated 401, cross-user 404, CSRF 403, token giả 401
"""

import io
import json
import os
import sys
import time
import urllib.request
import uuid
from http.cookiejar import CookieJar

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8001")
EMAIL = os.environ.get("E2E_EMAIL") or f"e2e-{uuid.uuid4().hex[:8]}@test.dev"
PASSWORD = "E2ePassw0rd!2026"

# Cookie jar giữ session (HttpOnly access_token + csrf_token)
_jar = CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def call(method: str, path: str, body: dict | None = None, expect: int | None = None, use_auth: bool = True):
    headers = {"Content-Type": "application/json"}
    if use_auth and method not in ("GET", "HEAD"):
        csrf = next((c.value for c in _jar if c.name == "csrf_token"), "")
        if csrf:
            headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    opener = _opener if use_auth else urllib.request.build_opener()
    try:
        with opener.open(req) as res:
            status = res.status
            raw = res.read().decode()
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode()
        data = json.loads(raw) if raw else {}
    if expect is not None:
        assert status == expect, f"{method} {path} -> {status} (expect {expect}): {data}"
    return status, data


results = []


def step(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# 0. AUTH — đăng ký (nếu đã có thì đăng nhập)
st, user = call("POST", "/v1/auth/register", {"email": EMAIL, "password": PASSWORD})
if st == 409:
    st, user = call("POST", "/v1/auth/login", {"email": EMAIL, "password": PASSWORD})
step("0. Dang ky/dang nhap hop le", st in (201, 200) and user.get("email") == EMAIL, f"status={st} user={user.get('email', '?')}")

st, me = call("GET", "/v1/auth/me")
step("0b. Session ton tai (/me)", st == 200 and me.get("email") == EMAIL, f"email={me.get('email', '?')}")

# 0c. Unauthenticated request → 401
st, _ = call("GET", "/v1/courses/crs_00000000-0000-0000-0000-000000000000", use_auth=False)
step("0c. Khong auth -> 401", st == 401, f"status={st}")

# 0d. CSRF thiếu → 403 (đã đăng nhập nhưng không header)
req = urllib.request.Request(
    f"{BASE}/v1/courses",
    method="POST",
    headers={"Content-Type": "application/json"},
    data=json.dumps({"topic": "x", "clientCourseId": uuid.uuid4().hex[:20]}).encode(),
)
try:
    with _opener.open(req) as res:
        csrf_status = res.status
except urllib.error.HTTPError as e:
    csrf_status = e.code
step("0d. POST thieu CSRF -> 403", csrf_status == 403, f"status={csrf_status}")

# 1. Tạo course
st, course = call("POST", "/v1/courses", {"topic": "Python cho người mới", "clientCourseId": uuid.uuid4().hex[:20]}, 201)
step("1. Tao course (201)", st == 201, f"id={course['id'][:20]} status={course['status']}")
course_id = course["id"]

# Kiểm tra idempotency: tạo lại cùng clientCourseId
st2, course2 = call("POST", "/v1/courses", {"topic": "Python cho người mới", "clientCourseId": course["clientCourseId"]}, 201)
step("1b. Idempotent khi retry request", course2["id"] == course_id, f"same id={course2['id'] == course_id}")

# 2. Trả lời 5 câu phỏng vấn
st, interview = call("GET", f"/v1/courses/{course_id}/interview", None, 200)
step("2. Interview co 5 cau", len(interview["questions"]) == 5, f"completedCount={interview['completedCount']}")

for i in range(5):
    st, ans = call("POST", f"/v1/courses/{course_id}/interview/answer", {"position": i, "answer": f"Tôi muon hoc de lam du an, moi tim hieu {i}"}, 200)
step("2b. Tra loi 5 cau", ans["completedCount"] == 5, f"completedCount={ans['completedCount']}")

# 3. Proposal hợp lệ
st, proposal = call("GET", f"/v1/courses/{course_id}/proposal", None, 200)
p = proposal["payload"]
valid = bool(p["name"]) and len(p["units"]) >= 2 and len(p["outcomes"]) >= 2 and all(u["lessonTitles"] for u in p["units"])
step("3. Proposal co cau truc hop le", valid, f"name='{p['name'][:40]}' units={len(p['units'])} lessons={sum(len(u['lessonTitles']) for u in p['units'])}")

# 4. Approve
st, approve = call("POST", f"/v1/courses/{course_id}/approve", None, 202)
step("4. Duyet proposal (202)", st == 202, f"jobId={approve['jobId'][:20]}")

# 5. Poll generation
final = None
for _ in range(60):
    st, gen = call("GET", f"/v1/courses/{course_id}/generation", None, 200)
    if gen["status"] in ("ready", "failed"):
        final = gen
        break
    time.sleep(0.5)
step("5. Generation job ready", final is not None and final["status"] == "ready", f"status={final['status'] if final else 'timeout'} lessonsDone={final['lessonsDone'] if final else '-'}/{final['lessonsTotal'] if final else '-'}")

# 6. Course detail >= 2 lessons
st, detail = call("GET", f"/v1/courses/{course_id}", None, 200)
lessons = [l for u in detail["units"] for l in u["lessons"]]
step("6. >= 2 bai hoc duoc sinh", len(lessons) >= 2, f"lessons={len(lessons)}")

# 7. Mở lesson đầu
lesson_id = lessons[0]["id"]
st, lesson = call("GET", f"/v1/lessons/{lesson_id}", None, 200)
block_types = {b["type"] for b in lesson["blocks"]}
step("7. Mo bai hoc (blocks day du)", st == 200 and "teach" in block_types, f"blocks={sorted(block_types)} contentVersion={lesson['contentVersion']}")

# 8. Làm quiz — trả lời đúng tất cả
answers = []
for idx, b in enumerate(lesson["blocks"]):
    t = b["type"]
    if t == "mc":
        answers.append({"index": idx, "answer": b["answerIndex"]})
    elif t == "blank":
        answers.append({"index": idx, "answer": b["answer"]})
    elif t == "order":
        answers.append({"index": idx, "answer": list(range(len(b["items"])))})
    elif t == "match":
        answers.append({"index": idx, "answer": {p[0]: p[1] for p in b["pairs"]}})
    elif t == "short":
        answers.append({"index": idx, "answer": b["acceptedAnswers"][0]})
    else:
        answers.append({"index": idx, "answer": None})

client_attempt = uuid.uuid4().hex[:20]
st, attempt = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": client_attempt,
    "contentVersion": lesson["contentVersion"],
    "durationMs": 42000,
    "answers": answers,
}, 201)
score = attempt["score"]
step("8. Quiz cham dung 100%", score["correct"] == score["total"] and score["total"] > 0, f"score={score['correct']}/{score['total']} xpEarned={attempt['rewards']['xpEarned']}")

# 8b. Idempotency attempt
st, dup = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": client_attempt,
    "contentVersion": lesson["contentVersion"],
    "answers": answers,
}, 201)
step("8b. Attempt idempotent (duplicate)", dup["duplicate"] is True and dup["score"] == score, "")

# 9. "Reload trang" — GET lại lesson + course, dữ liệu vẫn còn
st, lesson_reload = call("GET", f"/v1/lessons/{lesson_id}", None, 200)
st, detail_reload = call("GET", f"/v1/courses/{course_id}", None, 200)
lessons_reload = [l for u in detail_reload["units"] for l in u["lessons"]]
data_persisted = (
    lesson_reload["title"] == lesson["title"]
    and len(lessons_reload) == len(lessons)
    and lesson_reload["contentVersion"] == lesson["contentVersion"]
)
step("9. Reload khong mat du lieu", data_persisted, f"lessons sau reload={len(lessons_reload)}")

# ---- Case lỗi ----

# B. User khác (đăng nhập riêng) truy cập course không thuộc quyền → 404
OTHER_EMAIL = f"e2e-other-{uuid.uuid4().hex[:8]}@test.dev"
other_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def other_call(method, path, body=None):
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(f"{BASE}{path}", method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with other_opener.open(req) as res:
            return res.status, json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


st, _ = other_call("POST", "/v1/auth/register", {"email": OTHER_EMAIL, "password": PASSWORD})
st, _ = other_call("GET", f"/v1/courses/{course_id}")
step("B. User khac truy cap course -> 404", st == 404, f"status={st}")
st, _ = other_call("GET", f"/v1/lessons/{lesson_id}")
step("B2. User khac truy cap lesson -> 404", st == 404, f"status={st}")

# C. interview answer position sai → 422
st, _ = call("POST", f"/v1/courses/{course_id}/interview/answer", {"position": 99, "answer": "x"})
step("C. Vi tri interview sai -> 422", st == 422, f"status={st}")

# D. Course id không tồn tại
st, _ = call("GET", "/v1/courses/crs_00000000-0000-0000-0000-000000000000")
step("D. Course khong ton tai -> 404", st == 404, f"status={st}")

# E. Token giả mạo (cookie forged) → 401
forged_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
req = urllib.request.Request(f"{BASE}/v1/auth/me")
# thêm cookie giả thủ công
from http.cookiejar import Cookie

forged_cookie = Cookie(0, "access_token", "forged.token.value", None, False, "127.0.0.1", False, False, "/", True, False, None, False, None, None, {})
forged_jar = CookieJar()
forged_jar.set_cookie(forged_cookie)
forged_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(forged_jar))
try:
    with forged_opener.open(req) as res:
        forged_status = res.status
except urllib.error.HTTPError as e:
    forged_status = e.code
step("E. Token gia mao -> 401", forged_status == 401, f"status={forged_status}")

print()
passed = sum(1 for _, ok, _ in results if ok)
print(f"===== KET QUA: {passed}/{len(results)} PASS =====")
sys.exit(0 if passed == len(results) else 1)
