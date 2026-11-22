"""Acceptance criterion 1: TUTOR_ENABLED=false => 503 TUTOR_DISABLED.

Real HTTP against a running backend (default :8001). Registers a throwaway user,
then POSTs a tutor message. The 503 gate runs before any course lookup, so the
course id only has to be syntactically valid.
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
jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def csrf() -> str:
    return next((c.value for c in jar if c.name == "csrf_token"), "")


def post(path: str, body: dict, with_csrf: bool = True):
    headers = {"Content-Type": "application/json"}
    if with_csrf and csrf():
        headers["X-CSRF-Token"] = csrf()
    req = urllib.request.Request(
        f"{BASE}{path}", method="POST", headers=headers, data=json.dumps(body).encode()
    )
    try:
        with opener.open(req) as res:
            return res.status, dict(res.headers), res.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


email = f"tutor-off-{uuid.uuid4().hex[:8]}@test.dev"
st, _, raw = post(
    "/v1/auth/register",
    {"email": email, "password": "TutorOffPassw0rd!2026"},
    with_csrf=False,
)
print(f"[register] status={st}")
if st not in (200, 201):
    print(raw[:400])
    sys.exit(1)

status, _, body = post(
    "/v1/courses/00000000-0000-0000-0000-000000000000/tutor/messages",
    {
        "clientMessageId": uuid.uuid4().hex[:16],
        "threadId": None,
        "text": "probe",
        "contextRef": {
            "lessonId": "00000000-0000-0000-0000-000000000000",
            "blockIndex": 0,
        },
    },
)
print(f"[tutor-off] status={status} body={body[:300]}")
code = None
try:
    code = json.loads(body).get("detail", {}).get("code")
except Exception:
    pass
ok = status == 503 and code == "TUTOR_DISABLED"
print(f"RESULT={'PASS' if ok else 'FAIL'} code={code}")
sys.exit(0 if ok else 1)
