"""E2E acceptance verification — chạy thật qua HTTP với uvicorn server đang chạy.

Kịch bản theo Acceptance Criteria:
1. Nhập chủ đề "Python cho người mới"
2. Trả lời 5 câu phỏng vấn
3. Nhận proposal có cấu trúc hợp lệ
4. Duyệt proposal
5. Theo dõi job generation
6. Nhận >= 2 bài học
7. Mở và học một bài
8. Làm quiz và lưu kết quả
9. Tải lại trang mà không mất dữ liệu (GET lại lesson + attempts tồn tại)
"""

import io
import os
import json
import sys
import time
import urllib.request
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8001")
USER = f"e2e-user-{uuid.uuid4().hex[:8]}"


def call(method: str, path: str, body: dict | None = None, expect: int | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"Content-Type": "application/json", "X-User-Id": USER},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req) as res:
            status = res.status
            data = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        status = e.code
        data = json.loads(e.read().decode())
    if expect is not None:
        assert status == expect, f"{method} {path} -> {status} (expect {expect}): {data}"
    return status, data


results = []


def step(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


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
# A. Request trùng course (đã test 1b)

# B. Người dùng khác truy cập course không thuộc quyền
OTHER = f"other-user-{uuid.uuid4().hex[:8]}"
req = urllib.request.Request(
    f"{BASE}{course_id and '/v1/courses/' + course_id}",
    headers={"Content-Type": "application/json", "X-User-Id": OTHER},
)
try:
    with urllib.request.urlopen(req) as res:
        other_status = res.status
except urllib.error.HTTPError as e:
    other_status = e.code
step("B. User khac truy cap course -> 404", other_status == 404, f"status={other_status}")

# Lesson cũng vậy
req = urllib.request.Request(
    f"{BASE}/v1/lessons/{lesson_id}",
    headers={"Content-Type": "application/json", "X-User-Id": OTHER},
)
try:
    with urllib.request.urlopen(req) as res:
        other_status = res.status
except urllib.error.HTTPError as e:
    other_status = e.code
step("B2. User khac truy cap lesson -> 404", other_status == 404, f"status={other_status}")

# C. Dữ liệu AI sai schema → provider fail → job failed (dùng topic quá dài gây lỗi? Mock không lỗi)
# Thay bằng: interview answer position sai → 422
st, _ = call("POST", f"/v1/courses/{course_id}/interview/answer", {"position": 99, "answer": "x"})
step("C. Vi tri interview sai -> 422", st == 422, f"status={st}")

# D. Course id không tồn tại
st, _ = call("GET", "/v1/courses/crs_00000000-0000-0000-0000-000000000000")
step("D. Course khong ton tai -> 404", st == 404, f"status={st}")

print()
passed = sum(1 for _, ok, _ in results if ok)
print(f"===== KET QUA: {passed}/{len(results)} PASS =====")
sys.exit(0 if passed == len(results) else 1)
