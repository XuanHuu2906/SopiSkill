"""E2E acceptance verification — chạy thật qua HTTP với server đang chạy.

Kịch bản theo Acceptance Criteria:
0. Đăng ký + đăng nhập hợp lệ (cookie auth) — bắt buộc trước mọi API call
1. Nhập chủ đề "Python cho người mới"
2. Trả lời 5 câu phỏng vấn
3. Nhận proposal có cấu trúc hợp lệ
4. Duyệt proposal
5. Theo dõi job generation
6. Nhận >= 2 bài học
7. Mở bài học — public blocks KHÔNG được chứa answer key (P1.1)
8. Làm quiz đúng 100% — đáp án lấy từ private content trong DB (server-side),
   không đọc từ public payload
9. Tải lại trang mà không mất dữ liệu + progress tính từ attempts (P1.1)
+ Case lỗi: unauthenticated 401, cross-user 404, CSRF 403, token giả 401

Biến môi trường:
  E2E_BASE         — mặc định http://127.0.0.1:8001
  E2E_PG_DSN       — DSN PostgreSQL để đọc private lesson content (test harness,
                     KHÔNG dùng trong app). Mặc định trỏ port host của compose db.
                     Nếu không kết nối được, script FAIL rõ ràng thay vì đoán đáp án.
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
PG_DSN = os.environ.get(
    "E2E_PG_DSN", "postgresql://ailp:ailp_password@127.0.0.1:5433/ailp"
)
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


def _connect_pg():
    import psycopg

    return psycopg.connect(PG_DSN, connect_timeout=5)


def load_private_lesson(lesson_id: str):
    """Đọc `lessons.content` (private server-side) để dựng đáp án đúng.

    Đây là test harness chạy trên DB — KHÔNG phải đường đi của app. Nhờ vậy test
    không "tự chứng minh" bằng cách đọc answer key lộ qua API.
    """
    lid = lesson_id.removeprefix("lsn_")
    with _connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT content, content_version FROM lessons WHERE id = %s", (lid,)
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"lesson {lid} không có trong DB test")
    content, version = row
    if isinstance(content, str):
        content = json.loads(content)
    return content or [], int(version)


def public_answer_is_leaked(block: dict) -> bool:
    return any(
        key in block for key in ("answerIndex", "answer", "acceptedAnswers", "pairs")
    )


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

# 5b. P1.2 — job được dispatch bởi broker (không phải inline) và chỉ claim 1 lần
gen_final = final or {}
step(
    "5b. Job dispatched + 1 lan claim",
    gen_final.get("dispatched") is True and gen_final.get("attempts") == 1,
    f"dispatched={gen_final.get('dispatched')} attempts={gen_final.get('attempts')}",
)

# 5c. P1.2 — approve lai khi khong co job active: course ready -> duoc phep retry,
# va retry tao job MOI (khong dung job cu).
st, retry = call("POST", f"/v1/courses/{course_id}/retry", None, 202)
step("5c. Retry tao job moi", retry["jobId"] != approve["jobId"], f"jobId={retry['jobId'][:20]}")
for _ in range(60):
    st, gen2 = call("GET", f"/v1/courses/{course_id}/generation", None, 200)
    if gen2["status"] in ("ready", "failed"):
        break
    time.sleep(0.5)
step(
    "5d. Retry khong pha bai da hoc",
    gen2["status"] == "ready",
    f"status={gen2['status']} attempts={gen2.get('attempts')}",
)

# 6. Course detail >= 2 lessons
st, detail = call("GET", f"/v1/courses/{course_id}", None, 200)
lessons = [l for u in detail["units"] for l in u["lessons"]]
step("6. >= 2 bai hoc duoc sinh", len(lessons) >= 2, f"lessons={len(lessons)}")

# 7. Mở lesson đầu
lesson_id = lessons[0]["id"]
st, lesson = call("GET", f"/v1/lessons/{lesson_id}", None, 200)
block_types = {b["type"] for b in lesson["blocks"]}
step("7. Mo bai hoc (blocks day du)", st == 200 and "teach" in block_types, f"blocks={sorted(block_types)} contentVersion={lesson['contentVersion']}")

# 7b. P1.1 — public payload KHÔNG được lộ answer key (cả 5 loại quiz)
leaked = [b["type"] for b in lesson["blocks"] if public_answer_is_leaked(b)]
step("7b. GET lesson khong lo answer key", not leaked, f"leaked={leaked}")

# 8. Làm quiz — đáp án dựng từ private content trong DB, không từ public payload
private_blocks, private_version = load_private_lesson(lesson_id)
assert private_version == lesson["contentVersion"], (
    f"version lệch: public={lesson['contentVersion']} db={private_version}"
)

answers = []
for idx, b in enumerate(private_blocks):
    t = b["type"]
    if t == "mc":
        answers.append({"index": idx, "answer": int(b["answerIndex"])})
    elif t == "blank":
        answers.append({"index": idx, "answer": b["answer"]})
    elif t == "order":
        pub = lesson["blocks"][idx]
        text_to_id = {item["text"]: item["id"] for item in pub["items"]}
        answers.append({"index": idx, "answer": [text_to_id[x] for x in b["items"]]})
    elif t == "match":
        pub = lesson["blocks"][idx]
        left_ids = {item["text"]: item["id"] for item in pub["lefts"]}
        right_ids = {item["text"]: item["id"] for item in pub["rights"]}
        answers.append(
            {"index": idx, "answer": {left_ids[l]: right_ids[r] for l, r in b["pairs"]}}
        )
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

# 8b. Idempotency attempt — cùng clientAttemptId không cộng XP lần 2
st, dup = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": client_attempt,
    "contentVersion": lesson["contentVersion"],
    "answers": answers,
}, 201)
step("8b. Attempt idempotent (duplicate)", dup["duplicate"] is True and dup["score"] == score, "")

# 8c. P1.1 — nộp lại bằng id mới không farm XP
st, again = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": uuid.uuid4().hex[:20],
    "contentVersion": lesson["contentVersion"],
    "answers": answers,
}, 201)
step("8c. Nop lai khong farm XP", again["rewards"]["xpEarned"] == 0, f"xpEarned={again['rewards']['xpEarned']}")

# 8d. P1.1 — client không thể tự khai `correct`/answer key
forge_answers = [{"index": a["index"], "answer": "sai", "correct": True} for a in answers]
st, forged = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": uuid.uuid4().hex[:20],
    "contentVersion": lesson["contentVersion"],
    "answers": forge_answers,
})
# Contract: field lạ bị từ chối (422) hoặc bị bỏ qua — điểm luôn do server chấm.
forged_ok = st == 422 or (st == 201 and forged.get("score", {}).get("correct") == 0)
step("8d. Client gui correct=true khong doi diem", forged_ok, f"status={st} score={forged.get('score')}")

# 9. "Reload trang" — GET lại lesson + course; progress tính từ attempts (P1.1)
st, lesson_reload = call("GET", f"/v1/lessons/{lesson_id}", None, 200)
st, detail_reload = call("GET", f"/v1/courses/{course_id}", None, 200)
lessons_reload = [l for u in detail_reload["units"] for l in u["lessons"]]
progress = detail_reload["progress"]
data_persisted = (
    lesson_reload["title"] == lesson["title"]
    and len(lessons_reload) == len(lessons)
    and lesson_reload["contentVersion"] == lesson["contentVersion"]
)
step("9. Reload khong mat du lieu", data_persisted, f"lessons sau reload={len(lessons_reload)}")
step(
    "9b. Progress tinh tu attempt",
    progress["completed"] >= 1
    and progress["total"] == len(lessons_reload)
    and 0 < progress["percent"] <= 100,
    f"progress={progress}",
)
done = [l["id"] for u in detail_reload["units"] for l in u["lessons"] if l.get("completed")]
step("9c. Lesson da hoc duoc danh dau", lesson_id in done, f"completed_ids={len(done)}")

# 9d. P1.1 — stale contentVersion -> 409
st, stale = call("POST", f"/v1/lessons/{lesson_id}/attempts", {
    "clientAttemptId": uuid.uuid4().hex[:20],
    "contentVersion": lesson["contentVersion"] + 99,
    "answers": answers,
})
step("9d. Stale contentVersion -> 409", st == 409, f"status={st}")

# 10. P1.3 — dashboard "Khóa học của tôi" scoped theo user + resume link
st, my_courses = call("GET", "/v1/courses?limit=50&offset=0", None, 200)
ids = [c["id"] for c in my_courses["items"]]
item = next((c for c in my_courses["items"] if c["id"] == course_id), None)
step(
    "10. Dashboard chi tra course cua user",
    course_id in ids and my_courses["total"] >= 1,
    f"total={my_courses['total']} items={len(my_courses['items'])}",
)
step(
    "10b. Dashboard co tien do + resume",
    item is not None
    and item["progress"]["completed"] >= 1
    and (item["resumeLessonId"] is not None or item["progress"]["completed"] == item["progress"]["total"]),
    f"progress={item['progress'] if item else None} resume={(item or {}).get('resumeLessonId')}",
)

# 10c. Pagination contract
st, page = call("GET", "/v1/courses?limit=1&offset=0", None, 200)
step(
    "10c. Dashboard phan trang dung",
    len(page["items"]) == 1 and page["total"] == my_courses["total"],
    f"limit=1 items={len(page['items'])} hasMore={page['hasMore']}",
)

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

# B3. P1.3 — session isolation: user B (browser/tab khác) không thấy course của A
#      trong dashboard, kể cả khi dùng chung máy (cache phía client phải reset).
st, other_courses = other_call("GET", "/v1/courses?limit=50&offset=0")
other_ids = [c["id"] for c in other_courses.get("items", [])]
step(
    "B3. Session isolation: B khong thay course cua A",
    course_id not in other_ids,
    f"B_total={other_courses.get('total')} leaked={course_id in other_ids}",
)

# B4. P1.3 — B không đọc được generation/proposal/interview của A
checks = {}
for name, path in (
    ("generation", f"/v1/courses/{course_id}/generation"),
    ("proposal", f"/v1/courses/{course_id}/proposal"),
    ("interview", f"/v1/courses/{course_id}/interview"),
):
    st, _ = other_call("GET", path)
    checks[name] = st
step(
    "B4. B bi chan moi endpoint con cua A",
    all(code == 404 for code in checks.values()),
    f"status={checks}",
)

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
