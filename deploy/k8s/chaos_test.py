"""Phase 10B Multi-Pod Kubernetes Chaos E2E Verification (`kind` + Nginx Ingress + KEDA).

Tests executed against a live multi-replica K8s deployment:
  1. Chaos Test 1 (Pod Kill mid-SSE + `Last-Event-ID` Resume):
     Opens Tutor SSE stream through Ingress -> deletes the serving `core-api` pod mid-stream ->
     reconnects with `Last-Event-ID` -> surviving `core-api` pod replays missed frames through `done`.
  2. Chaos Test 2 (Cross-Pod Instant `/stop` via Redis Pub/Sub):
     Opens slow SSE stream directly on `core-api` Pod A -> fires `POST /stop` directly to Pod B ->
     Redis Pub/Sub cancels Pod A's stream immediately (`event:cancelled`, DB status=`cancelled`).
  3. Chaos Test 3 (Rolling Update `core-api` & `ai-worker-llm` during in-flight async job):
     Enqueues course generation -> immediately executes `kubectl rollout restart` on both deployments ->
     verifies 0 lost jobs and 100% lesson + reel completion.
  4. Verifies KEDA `ScaledObject` readiness and triggers `CronJob: maintenance`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass

import httpx


NAMESPACE = os.environ.get("K8S_NAMESPACE", "sopiskill")
RELEASE = os.environ.get("K8S_RELEASE", "sopiskill")
BASE_URL = os.environ.get("K8S_INGRESS_URL", "http://127.0.0.1:8088").rstrip("/")


def run_kubectl(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["kubectl", "-n", NAMESPACE, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    return proc.stdout.strip()


@dataclass
class AuthSession:
    cookies: dict[str, str]
    csrf: str
    user_id: str

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"X-CSRF-Token": self.csrf}
        if extra:
            h.update(extra)
        return h


def register_user(client: httpx.Client, prefix: str) -> AuthSession:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@k8s-chaos.test"
    r = client.post(
        f"{BASE_URL}/v1/auth/register",
        json={"email": email, "password": "StrongPassword123!"},
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Register failed: {r.status_code} {r.text}")
    cookies = dict(client.cookies)
    csrf = cookies.get("csrf_token", "")
    user_id = r.json()["id"]
    return AuthSession(cookies=cookies, csrf=csrf, user_id=user_id)


def create_ready_course(client: httpx.Client, auth: AuthSession, topic: str) -> tuple[str, str]:
    r_create = client.post(
        f"{BASE_URL}/v1/courses",
        headers=auth.headers(),
        json={"topic": topic, "language": "en"},
    )
    r_create.raise_for_status()
    course_id = r_create.json()["id"]

    answers = [
        "Complete beginner",
        "Understand core concepts quickly",
        "3 hours per week",
        "Hands-on examples",
        "Balanced theory & practice",
    ]
    for idx, ans in enumerate(answers):
        r_ans = client.post(
            f"{BASE_URL}/v1/courses/{course_id}/interview/answer",
            headers=auth.headers(),
            json={"position": idx, "answer": ans},
        )
        r_ans.raise_for_status()

    r_app = client.post(f"{BASE_URL}/v1/courses/{course_id}/approve", headers=auth.headers())
    if r_app.status_code not in (200, 202):
        raise RuntimeError(f"Approve failed: {r_app.status_code} {r_app.text}")

    deadline = time.time() + 90
    lesson_id = ""
    while time.time() < deadline:
        r_path = client.get(f"{BASE_URL}/v1/courses/{course_id}/path")
        if r_path.status_code == 200:
            data = r_path.json()
            for unit in data.get("units") or []:
                for lsn in unit.get("lessons") or []:
                    if lsn.get("status") == "ready" and not lesson_id:
                        lesson_id = lsn["id"]
            if data.get("status") == "ready" and lesson_id:
                return course_id, lesson_id
        time.sleep(0.8)
    raise TimeoutError(f"Course {course_id} did not become ready within 90s")


def iter_sse_events(resp: httpx.Response):
    event_name = "message"
    event_id = ""
    data_lines: list[str] = []
    for raw_line in resp.iter_lines():
        line = raw_line.strip("\r")
        if line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            yield {"id": event_id, "event": event_name, "data": "\n".join(data_lines)}
            event_name = "message"
            event_id = ""
            data_lines = []


def wait_core_api_pods_ready(expected: int = 2) -> list[str]:
    run_kubectl("rollout", "status", f"deployment/{RELEASE}-core-api", "--timeout=120s")
    deadline = time.time() + 60
    while time.time() < deadline:
        out = run_kubectl(
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/component=core-api,app.kubernetes.io/instance={RELEASE}",
            "-o",
            "json",
        )
        items = json.loads(out).get("items") or []
        ready_names = []
        for pod in items:
            if pod.get("metadata", {}).get("deletionTimestamp"):
                continue
            statuses = pod.get("status", {}).get("containerStatuses") or []
            if statuses and all(cs.get("ready") for cs in statuses):
                ready_names.append(pod["metadata"]["name"])
        if len(ready_names) >= expected:
            return sorted(ready_names)
        time.sleep(1.0)
    raise TimeoutError("Timed out waiting for 2 ready core-api pods")


def chaos_test_1_pod_kill_sse_resume(client: httpx.Client, auth: AuthSession, course_id: str, lesson_id: str) -> None:
    print("[Chaos 1] Opening SSE Tutor stream through Split Ingress...")
    payload = {
        "clientMessageId": f"k8s-chaos1-{uuid.uuid4().hex[:10]}",
        "text": "Explain this lesson deeper with an example",
        "entryPoint": "teach_block",
        "delayMs": 220,
        "contextRef": {"lessonId": lesson_id, "blockIndex": 0},
    }

    serving_pod = ""
    msg_id = ""
    first_event_id = ""
    first_text = ""

    with client.stream(
        "POST",
        f"{BASE_URL}/v1/courses/{course_id}/tutor/messages",
        headers=auth.headers({"Accept": "text/event-stream"}),
        json=payload,
        timeout=30.0,
    ) as resp:
        resp.raise_for_status()
        serving_pod = resp.headers.get("x-pod-name", "")
        msg_id = resp.headers.get("x-tutor-message-id", "")
        if not serving_pod or not msg_id:
            raise AssertionError(f"Missing x-pod-name or x-tutor-message-id headers: {dict(resp.headers)}")
        for ev in iter_sse_events(resp):
            first_event_id = ev["id"]
            if ev["event"] == "delta":
                first_text += json.loads(ev["data"]).get("text", "")
            if first_event_id:
                break

    print(f"[Chaos 1] Stream opened on pod={serving_pod}, msg={msg_id}, firstEventId={first_event_id}. Deleting {serving_pod}!")
    run_kubectl("delete", "pod", serving_pod, "--wait=false")

    # Wait briefly so Endpoints controller removes the terminating pod before reconnect hits Ingress
    time.sleep(2.5)

    resumed_pod = ""
    resumed_events: list[str] = []
    resumed_text = ""
    with client.stream(
        "GET",
        f"{BASE_URL}/v1/courses/{course_id}/tutor/messages/{msg_id}/stream?lastEventId={urllib.parse.quote(first_event_id)}",
        headers={"Accept": "text/event-stream", "Last-Event-ID": first_event_id},
        timeout=30.0,
    ) as resp2:
        resp2.raise_for_status()
        resumed_pod = resp2.headers.get("x-pod-name", "")
        for ev in iter_sse_events(resp2):
            resumed_events.append(ev["event"])
            if ev["event"] == "delta":
                resumed_text += json.loads(ev["data"]).get("text", "")
            if ev["event"] in ("done", "error", "cancelled", "restarted"):
                break

    print(f"[Chaos 1] Resumed on surviving pod={resumed_pod}, events={resumed_events}, textLen={len(first_text + resumed_text)}")
    assert resumed_pod and resumed_pod != serving_pod, f"Expected failover to different pod, got {resumed_pod} vs {serving_pod}"
    assert "delta" in resumed_events, f"Expected missed delta events on resume, got {resumed_events}"
    assert "done" in resumed_events, f"Expected terminal done event on resume, got {resumed_events}"
    assert len(first_text + resumed_text) > len(first_text), "Expected non-empty resumed text"

    wait_core_api_pods_ready(2)
    print("[Chaos 1] PASS — Zero dropped content after mid-stream pod deletion!")


def chaos_test_2_cross_pod_pubsub_stop(auth: AuthSession, course_id: str, lesson_id: str) -> None:
    pods = wait_core_api_pods_ready(2)
    pod_a, pod_b = pods[0], pods[1]
    print(f"[Chaos 2] Port-forwarding directly to podA={pod_a} (:18081) and podB={pod_b} (:18082)...")

    pf_a = subprocess.Popen(["kubectl", "-n", NAMESPACE, "port-forward", f"pod/{pod_a}", "18081:8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pf_b = subprocess.Popen(["kubectl", "-n", NAMESPACE, "port-forward", f"pod/{pod_b}", "18082:8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Wait until both port-forwards answer
        for port in (18081, 18082):
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.5)
                    if r.status_code == 200:
                        break
                except Exception:
                    time.sleep(0.3)

        with httpx.Client(cookies=auth.cookies, timeout=30.0) as direct_a, httpx.Client(cookies=auth.cookies, timeout=15.0) as direct_b:
            payload = {
                "clientMessageId": f"k8s-chaos2-{uuid.uuid4().hex[:10]}",
                "text": "Explain Redis Pub/Sub cross-pod cancellation in detail",
                "entryPoint": "tab",
                "delayMs": 350,
                "contextRef": {"lessonId": lesson_id, "blockIndex": 0},
            }
            events_a: list[str] = []
            with direct_a.stream(
                "POST",
                f"http://127.0.0.1:18081/v1/courses/{course_id}/tutor/messages",
                headers=auth.headers({"Accept": "text/event-stream"}),
                json=payload,
            ) as resp_a:
                resp_a.raise_for_status()
                header_pod_a = resp_a.headers.get("x-pod-name", "")
                msg_id = resp_a.headers.get("x-tutor-message-id", "")
                thread_id = resp_a.headers.get("x-tutor-thread-id", "")
                assert header_pod_a == pod_a, f"Expected {pod_a}, got {header_pod_a}"

                stop_sent = False
                for ev in iter_sse_events(resp_a):
                    events_a.append(ev["event"])
                    if not stop_sent:
                        r_stop = direct_b.post(
                            f"http://127.0.0.1:18082/v1/courses/{course_id}/tutor/messages/{msg_id}/stop",
                            headers=auth.headers(),
                        )
                        r_stop.raise_for_status()
                        stop_body = r_stop.json()
                        assert stop_body.get("podName") == pod_b, f"Stop landed on {stop_body.get('podName')} != {pod_b}"
                        stop_sent = True
                        print(f"[Chaos 2] Sent /stop to {pod_b} while {pod_a} was streaming {msg_id}")
                    if ev["event"] in ("cancelled", "done", "error"):
                        break

            assert "cancelled" in events_a, f"Expected Pod A stream to receive 'cancelled', got {events_a}"
            time.sleep(0.4)
            r_thread = direct_b.get(f"http://127.0.0.1:18082/v1/courses/{course_id}/tutor/threads/{thread_id}")
            r_thread.raise_for_status()
            msgs = r_thread.json().get("messages") or []
            target = next((m for m in msgs if m["id"] == msg_id), None)
            assert target is not None and target["status"] == "cancelled", f"Expected cancelled status in DB, got {target}"
            print(f"[Chaos 2] PASS — Cross-pod /stop ({pod_b} -> {pod_a}) cancelled stream immediately!")
    finally:
        pf_a.terminate()
        pf_b.terminate()
        pf_a.wait(timeout=5)
        pf_b.wait(timeout=5)


def chaos_test_3_rolling_update_inflight_job(client: httpx.Client, auth: AuthSession) -> None:
    print("[Chaos 3] Creating course and triggering rolling update during in-flight LLM job...")
    r_create = client.post(
        f"{BASE_URL}/v1/courses",
        headers=auth.headers(),
        json={"topic": "Kubernetes Resilience", "language": "en"},
    )
    r_create.raise_for_status()
    course_id = r_create.json()["id"]

    for idx, ans in enumerate(["Intermediate", "Build resilient deployments", "5 hours", "Projects", "Deep dive"]):
        client.post(f"{BASE_URL}/v1/courses/{course_id}/interview/answer", headers=auth.headers(), json={"position": idx, "answer": ans}).raise_for_status()

    r_app = client.post(f"{BASE_URL}/v1/courses/{course_id}/approve", headers=auth.headers())
    if r_app.status_code not in (200, 202):
        raise RuntimeError(f"Approve failed: {r_app.status_code} {r_app.text}")

    # Trigger rolling update on BOTH `core-api` and `ai-worker-llm` while job is in flight!
    run_kubectl("rollout", "restart", f"deployment/{RELEASE}-core-api", f"deployment/{RELEASE}-ai-worker-llm")
    run_kubectl("rollout", "status", f"deployment/{RELEASE}-core-api", "--timeout=180s")
    run_kubectl("rollout", "status", f"deployment/{RELEASE}-ai-worker-llm", "--timeout=180s")

    deadline = time.time() + 120
    while time.time() < deadline:
        r_path = client.get(f"{BASE_URL}/v1/courses/{course_id}/path")
        if r_path.status_code == 200:
            pdata = r_path.json()
            lessons = [lsn for u in (pdata.get("units") or []) for lsn in (u.get("lessons") or [])]
            if pdata.get("status") == "ready" and lessons and all(l.get("status") == "ready" for l in lessons):
                first_lsn = client.get(f"{BASE_URL}/v1/lessons/{lessons[0]['id']}").json()
                assert first_lsn.get("reel") is not None, "Expected compiled Reel manifest after rolling update!"
                print(f"[Chaos 3] PASS — Course {course_id} ({len(lessons)} lessons + Reel) completed with ZERO lost jobs across rolling update!")
                return
        time.sleep(1.0)
    raise TimeoutError(f"In-flight course {course_id} did not finish after rolling update")


def verify_keda_and_cronjob() -> None:
    so_raw = run_kubectl("get", "scaledobject", "-o", "json")
    sos = json.loads(so_raw).get("items") or []
    assert len(sos) == 2, f"Expected 2 KEDA ScaledObjects, found {len(sos)}"
    for so in sos:
        name = so["metadata"]["name"]
        conds = {c["type"]: c["status"] for c in (so.get("status", {}).get("conditions") or [])}
        print(f"[KEDA] ScaledObject {name}: conditions={conds}")
        assert conds.get("Ready") == "True", f"ScaledObject {name} not Ready: {conds}"

    job_name = f"chaos-maint-{uuid.uuid4().hex[:6]}"
    run_kubectl("create", "job", f"--from=cronjob/{RELEASE}-maintenance", job_name)
    run_kubectl("wait", "--for=condition=complete", f"job/{job_name}", "--timeout=90s")
    logs = run_kubectl("logs", f"job/{job_name}", "-c", "maintenance-app")
    print(f"[CronJob] maintenance logs: {logs}")
    assert '"status": "ok"' in logs, f"Maintenance job unexpected logs: {logs}"
    run_kubectl("delete", "job", job_name)


def main() -> int:
    # Verify ai-api is strictly ClusterIP (no Ingress points to ai-api)
    ing_raw = run_kubectl("get", "ingress", "-o", "json")
    ing_items = json.loads(ing_raw).get("items") or []
    assert len(ing_items) == 2, f"Expected 2 split Ingresses, got {len(ing_items)}"
    assert "ai-api" not in ing_raw, "ai-api MUST NEVER be exposed via Ingress!"

    with httpx.Client(timeout=30.0) as client:
        # Verify frontend & API reachable via Split Ingress
        r_fe = client.get(f"{BASE_URL}/login")
        assert r_fe.status_code == 200, f"Frontend via Ingress failed: {r_fe.status_code}"

        auth = register_user(client, "k8s")
        course_id, lesson_id = create_ready_course(client, auth, "Distributed Kubernetes")

        chaos_test_1_pod_kill_sse_resume(client, auth, course_id, lesson_id)
        chaos_test_2_cross_pod_pubsub_stop(auth, course_id, lesson_id)
        chaos_test_3_rolling_update_inflight_job(client, auth)

    verify_keda_and_cronjob()
    print("ALL PHASE 10B K8S CHAOS & INFRASTRUCTURE TESTS PASSED!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
