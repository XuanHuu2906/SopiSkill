"""Phase 10A unit & integration tests: 2-Phase Narrated Reel Engine, Safe AST Plot & TTSProvider."""

from __future__ import annotations

import json
import pytest
import httpx
from fastapi.testclient import TestClient

from app.agents.figure_validator import compile_plot_scene_spec, evaluate_safe_math_ast
from app.agents.providers import MockProvider, OpenAICompatibleProvider
from app.agents.reel_compiler import ALLOWED_SCENE_KINDS, compile_lesson_reel
from app.agents.tts_provider import MockTTSProvider, TtsConfigError, get_tts_provider
from app.core.config import Settings, get_settings
from app.core.internal_auth import sign_internal_headers
from app.main import app
from app.rag.storage import MemorySourceStorage, SourceStorageError
from app.workers.worker_llm import handle_llm_job


def test_safe_ast_plot_compiler_segments_tangents_areas_and_blocks_injection():
    assert evaluate_safe_math_ast("x^2 - 2*x + 2", {"x": 1.0}) == pytest.approx(1.0)
    assert evaluate_safe_math_ast("__import__('os').system('id')", {"x": 1.0}) is None
    assert evaluate_safe_math_ast("eval('1+1')", {"x": 1.0}) is None
    assert evaluate_safe_math_ast("(1).__class__", {"x": 1.0}) is None

    compiled = compile_plot_scene_spec(
        {
            "xRange": [-1, 4],
            "yRange": [-1, 6],
            "functions": [
                {"expr": "x^2 - 2*x + 2", "label": "f(x)"},
                {"expr": "__import__('os').popen('id')", "label": "malicious"},
            ],
            "points": [{"x": 1, "y": 1, "label": "min"}],
            "tangents": [{"x": 2, "expr": "x^2 - 2*x + 2"}],
            "areas": [{"fromX": 0, "toX": 2, "expr": "x^2 - 2*x + 2"}],
        }
    )
    # Malicious expression stripped; safe curve compiled
    assert len(compiled["curves"]) == 1
    assert len(compiled["curves"][0]["segments"]) >= 1
    assert len(compiled["curves"][0]["segments"][0]) >= 10
    # Tangent at x=2 for x^2 - 2x + 2 has derivative 2*2 - 2 = 2.0
    assert len(compiled["tangents"]) == 1
    assert compiled["tangents"][0]["slope"] == pytest.approx(2.0, abs=1e-2)
    # Definite integral polygon compiled
    assert len(compiled["areas"]) == 1
    assert len(compiled["areas"][0]["polygon"]) >= 10


@pytest.mark.asyncio
async def test_mock_tts_provider_generates_valid_wav_and_monotonic_word_timings():
    tts = MockTTSProvider(Settings())
    res_vi = await tts.synthesize("Xin chào SopiSkill, cùng học hàm số.", language="vi")
    assert res_vi.content_type == "audio/wav"
    assert res_vi.audio_bytes[:4] == b"RIFF"
    assert res_vi.audio_bytes[8:12] == b"WAVE"
    assert res_vi.duration_ms >= 1200
    assert len(res_vi.words) == 7
    for idx, w in enumerate(res_vi.words):
        assert w.startMs < w.endMs
        if idx > 0:
            assert w.startMs >= res_vi.words[idx - 1].startMs

    # Fail-fast when cloud TTS selected without API key
    with pytest.raises(TtsConfigError):
        get_tts_provider(Settings(tts_provider="openai_compatible", tts_api_key=""))


@pytest.mark.asyncio
async def test_two_phase_reel_compiler_all_11_scenes_grounded_figure_and_zero_answer_keys():
    storage = MemorySourceStorage()
    lesson = {
        "title": "Bài 1: Đạo hàm & Tối ưu hóa",
        "blocks": [
            {
                "type": "teach",
                "title": "Đạo hàm là tốc độ biến thiên",
                "paragraphs": ["Đạo hàm đo độ dốc tiếp tuyến tại từng điểm."],
                "takeaway": "Tìm cực trị bằng cách giải f'(x) = 0.",
                "terms": [{"term": "Đạo hàm", "definition": "Giới hạn của tỷ số sai phân."}],
            },
            {
                "type": "mc",
                "question": "Đạo hàm của x^2 là gì?",
                "options": ["x", "2x", "x^2"],
                "answerIndex": 1,
            },
        ],
    }
    available_figures = [
        {
            "sourceId": "src_00000000000000000000000000000001",
            "figureId": "fig_calc_tangent_01",
            "caption": "Minh họa tiếp tuyến hàm bậc hai",
            "sourceTitle": "OpenStax Calculus Vol 1",
            "attribution": "OpenStax CC BY 4.0",
        }
    ]
    res = await compile_lesson_reel(
        course_id="crs_1234",
        lesson_id="lsn_5678",
        content_version=1,
        topic="Giải tích",
        lesson_title="Bài 1: Đạo hàm & Tối ưu hóa",
        lesson=lesson,
        language="vi",
        available_figures=available_figures,
        provider=MockProvider(),
        tts_provider=MockTTSProvider(Settings()),
        storage=storage,
    )

    manifest = res.manifest
    assert manifest["version"] == 1
    assert manifest["durationMs"] > 0
    kinds = [sc["kind"] for sc in manifest["scenes"]]
    expected_11 = {
        "title", "statement", "bullets", "term", "compare",
        "figure", "chart", "code", "equation", "plot", "ready",
    }
    assert expected_11.issubset(set(kinds))

    # Grounded textbook `sourceFigureId` resolved cleanly to server proxy URL
    fig_scene = next(sc for sc in manifest["scenes"] if sc["kind"] == "figure")
    assert fig_scene["sourceFigureId"] == "fig_calc_tangent_01"
    assert fig_scene["image"]["url"] == "/v1/library/figures/src_00000000000000000000000000000001/fig_calc_tangent_01"

    # Audio clips uploaded strictly under `reels-audio/{courseId}/{lessonId}/`
    assert len(res.media_calls) == len(manifest["scenes"])
    for mc in res.media_calls:
        assert mc["objectKey"].startswith("reels-audio/crs_1234/lsn_5678/")
        raw = await storage.get_bytes(mc["objectKey"])
        assert raw[:4] == b"RIFF"

    # Zero answer keys anywhere in manifest
    dumped = json.dumps(manifest)
    for forbidden in ("answerIndex", "acceptedAnswers", "answer_key", "solution"):
        assert forbidden not in dumped

    # Prefix cleanup safety
    with pytest.raises(SourceStorageError):
        await storage.delete_prefix("sources/evil/")
    deleted = await storage.delete_prefix("reels-audio/crs_1234/lsn_5678/")
    assert deleted == len(res.media_calls)


@pytest.mark.asyncio
async def test_reel_compiler_degrades_malformed_and_hallucinated_scenes_to_fallback():
    storage = MemorySourceStorage()
    bad_script = {
        "styleVersion": "v1",
        "scenes": [
            {"id": "s1", "kind": "unknown_kind", "title": "Oops", "beats": [{"say": "Fallback test."}]},
            {
                "id": "s2",
                "kind": "figure",
                "title": "Hallucinated figure",
                "sourceFigureId": "fig_does_not_exist",
                "beats": [{"say": "Hallucinated."}],
            },
            {
                "id": "s3",
                "kind": "plot",
                "title": "Evil plot",
                "plot": {"functions": [{"expr": "__import__('os').system('rm -rf /')"}]},
                "answerIndex": 2,  # injected answer key must be stripped!
                "beats": [{"say": "Bad expr."}],
            },
        ],
    }
    res = await compile_lesson_reel(
        course_id="crs_bad",
        lesson_id="lsn_bad",
        content_version=1,
        topic="Test",
        lesson_title="Bad Script",
        lesson={"title": "Bad", "blocks": []},
        language="en",
        available_figures=[],
        tts_provider=MockTTSProvider(Settings()),
        storage=storage,
        prebuilt_script=bad_script,
    )
    assert [sc["kind"] for sc in res.manifest["scenes"]] == ["fallback", "fallback", "fallback"]
    assert "answerIndex" not in json.dumps(res.manifest)


@pytest.mark.asyncio
async def test_agent6_deepseek_sdk_save_reel_script_tool_call():
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_bodies.append(body)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-reel-1",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_reel_1",
                                    "type": "function",
                                    "function": {
                                        "name": "save_reel_script",
                                        "arguments": json.dumps(
                                            {
                                                "styleVersion": "v1",
                                                "scenes": [
                                                    {
                                                        "id": "sc_1",
                                                        "kind": "title",
                                                        "title": "Gradient Descent",
                                                        "beats": [{"say": "Welcome to gradient descent."}],
                                                    },
                                                    {
                                                        "id": "sc_2",
                                                        "kind": "plot",
                                                        "title": "Loss curve",
                                                        "plot": {
                                                            "xRange": [-3, 3],
                                                            "yRange": [0, 9],
                                                            "functions": [{"expr": "x^2", "label": "L(w)=w^2"}],
                                                            "tangents": [{"x": 1.5, "expr": "x^2"}],
                                                        },
                                                        "beats": [{"say": "Follow the negative gradient down the parabola."}],
                                                    },
                                                    {
                                                        "id": "sc_3",
                                                        "kind": "ready",
                                                        "title": "Let's practice",
                                                        "beats": [{"say": "Ready to test your intuition?"}],
                                                    },
                                                ],
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 90, "total_tokens": 210},
            },
        )

    transport = httpx.MockTransport(handler)
    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=transport)

    res = await compile_lesson_reel(
        course_id="crs_ds",
        lesson_id="lsn_ds",
        content_version=1,
        topic="Gradient Descent",
        lesson_title="Gradient Descent Intuition",
        lesson={"title": "Gradient Descent", "blocks": [{"type": "teach", "title": "Slope", "paragraphs": ["Move downhill."]}]},
        language="en",
        provider=provider,
        tts_provider=MockTTSProvider(cfg),
        storage=MemorySourceStorage(),
        settings=cfg,
    )
    assert len(captured_bodies) == 1
    assert captured_bodies[0]["tool_choice"]["function"]["name"] == "save_reel_script"
    assert [sc["kind"] for sc in res.manifest["scenes"]] == ["title", "plot", "ready"]
    assert res.manifest["scenes"][1]["plot"]["tangents"][0]["slope"] == pytest.approx(3.0, abs=1e-2)
    assert res.usage.totalTokens == 210


def test_internal_reel_endpoints_hmac_and_path_traversal_guard():
    settings = get_settings()
    client = TestClient(app)

    compile_body = json.dumps(
        {
            "courseId": "crs_api1",
            "lessonId": "lsn_api1",
            "contentVersion": 1,
            "topic": "SQL Index",
            "lessonTitle": "B-Tree Basics",
            "language": "vi",
            "lesson": {"title": "B-Tree", "blocks": [{"type": "teach", "title": "Index", "paragraphs": ["B-Tree speeds up lookup."]}]},
        }
    ).encode("utf-8")
    headers = sign_internal_headers(
        method="POST",
        path_with_query="/internal/reels/compile",
        raw_body=compile_body,
        settings=settings,
    )
    headers["Content-Type"] = "application/json"
    r = client.post("/internal/reels/compile", content=compile_body, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    first_clip = data["mediaCalls"][0]["clipId"]

    # Fetch audio clip via signed GET
    audio_path = f"/internal/reels/audio/crs_api1/lsn_api1/{first_clip}"
    get_headers = sign_internal_headers(
        method="GET",
        path_with_query=audio_path,
        raw_body=b"",
        settings=settings,
    )
    r_audio = client.get(audio_path, headers=get_headers)
    assert r_audio.status_code == 200
    assert r_audio.headers["content-type"].startswith("audio/wav")
    assert r_audio.headers["x-content-type-options"] == "nosniff"
    assert r_audio.content[:4] == b"RIFF"

    # Invalid clip filename rejected with 400
    bad_path = "/internal/reels/audio/crs_api1/lsn_api1/bad.exe"
    bad_headers = sign_internal_headers(
        method="GET",
        path_with_query=bad_path,
        raw_body=b"",
        settings=settings,
    )
    assert client.get(bad_path, headers=bad_headers).status_code == 400

    # Delete audio clips cleanly
    del_path = "/internal/reels/audio/crs_api1/lsn_api1"
    del_headers = sign_internal_headers(
        method="DELETE",
        path_with_query=del_path,
        raw_body=b"",
        settings=settings,
    )
    r_del = client.delete(del_path, headers=del_headers)
    assert r_del.status_code == 200
    assert r_del.json()["deletedObjects"] == len(data["mediaCalls"])


@pytest.mark.asyncio
async def test_worker_llm_attaches_reel_manifest_when_enabled_and_skips_when_disabled():
    callbacks: list[tuple[str, dict]] = []

    class RecordingCallback:
        async def post_callback(self, path: str, payload: dict, correlation_id: str = ""):
            callbacks.append((path, payload))

    cfg = Settings(source_storage_backend="memory", reel_enabled=True)
    await handle_llm_job(
        {
            "jobId": "job_reel_on",
            "idempotencyKey": "idem_reel_on",
            "jobType": "generate_lesson",
            "courseId": "crs_w1",
            "ownerId": "usr_w1",
            "payload": {
                "topic": "Calculus",
                "language": "en",
                "unitTitle": "Unit 1",
                "lessonTitle": "Derivatives",
                "lessonIds": ["lsn_w1"],
                "reelEnabled": True,
            },
        },
        provider=MockProvider(),
        callback_client=RecordingCallback(),  # type: ignore[arg-type]
        settings=cfg,
    )
    lesson_ready_calls = [p for path, p in callbacks if path.endswith("/lesson-ready")]
    assert len(lesson_ready_calls) == 1
    assert "reelManifest" in lesson_ready_calls[0]
    assert len(lesson_ready_calls[0]["mediaCalls"]) >= 10

    # Disabled flag omits reelManifest cleanly
    callbacks.clear()
    await handle_llm_job(
        {
            "jobId": "job_reel_off",
            "idempotencyKey": "idem_reel_off",
            "jobType": "generate_lesson",
            "courseId": "crs_w2",
            "ownerId": "usr_w2",
            "payload": {
                "topic": "Calculus",
                "language": "en",
                "unitTitle": "Unit 1",
                "lessonTitle": "Derivatives",
                "lessonIds": ["lsn_w2"],
                "reelEnabled": False,
            },
        },
        provider=MockProvider(),
        callback_client=RecordingCallback(),  # type: ignore[arg-type]
        settings=cfg,
    )
    lesson_ready_off = [p for path, p in callbacks if path.endswith("/lesson-ready")]
    assert len(lesson_ready_off) == 1
    assert "reelManifest" not in lesson_ready_off[0]
