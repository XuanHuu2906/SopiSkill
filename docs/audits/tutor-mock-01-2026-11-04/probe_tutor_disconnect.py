"""GATE TUTOR-MOCK-01 — criterion 6 (negative stream), live attempt.

Opens a real tutor SSE stream, reads only the first few hundred bytes, then
closes the socket mid-stream. Then reloads the thread to see what the server
persisted. The mock provider yields without sleeping, so this may finish before
the close lands; whatever happens is recorded as an observation, not a pass.
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8001")
COURSE_ID = os.environ["E2E_COURSE_ID"]
LESSON_ID = os.environ["E2E_LESSON_ID"]
EMAIL = os.environ["E2E_USER_EMAIL"]
PASSWORD = os.environ["E2E_USER_PASSWORD"]

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def csrf() -> str:
    return next((c.value for c in jar if c.name == "csrf_token"), "")


opener.open(urllib.request.Request(
    f"{BASE}/v1/auth/login", method="POST",
    headers={"Content-Type": "application/json"},
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode())).read()

body = {
    "clientMessageId": uuid.uuid4().hex[:16],
    "threadId": None,
    "text": "Kể chi tiết về block này",
    "contextRef": {"lessonId": LESSON_ID, "blockIndex": 0},
}
req = urllib.request.Request(
    f"{BASE}/v1/courses/{COURSE_ID}/tutor/messages", method="POST",
    headers={"Content-Type": "application/json", "Accept": "text/event-stream",
             "X-CSRF-Token": csrf()},
    data=json.dumps(body).encode())

read_bytes = 0
thread_id = None
msg_id = None
try:
    with opener.open(req) as res:
        lowered = {k.lower(): v for k, v in res.headers.items()}
        thread_id = lowered.get("x-tutor-thread-id")
        msg_id = lowered.get("x-tutor-message-id")
        # Đọc một phần rồi ngắt — mô phỏng client đóng tab giữa stream.
        chunk = res.read(200)
        read_bytes = len(chunk)
        print(f"read {read_bytes} bytes then closing mid-stream")
except Exception as exc:  # noqa: BLE001
    print(f"stream read ended: {type(exc).__name__}: {exc}")

print(f"thread={thread_id} message={msg_id} bytes_read={read_bytes}")

# Cho server một nhịp để task nền ghi trạng thái cuối.
import time  # noqa: E402
time.sleep(2)

tid = thread_id.split("_", 1)[-1] if thread_id else ""
st, _, raw = None, None, ""
try:
    with opener.open(urllib.request.Request(
            f"{BASE}/v1/courses/{COURSE_ID}/tutor/threads/{tid}",
            headers={"Accept": "application/json"})) as res:
        st, raw = res.status, res.read().decode()
except urllib.error.HTTPError as e:
    st, raw = e.code, e.read().decode()

print(f"reload status={st}")
if st == 200:
    data = json.loads(raw)
    for m in data["messages"]:
        print(f"  role={m['role']} status={m['status']} len={len(m['content'])} "
              f"errorCode={m.get('errorCode')}")
    print(json.dumps({"observed": True, "threadId": tid, "bytesBeforeClose": read_bytes},
                     ensure_ascii=False))
else:
    print(raw[:300])
    print(json.dumps({"observed": False, "status": st}, ensure_ascii=False))
