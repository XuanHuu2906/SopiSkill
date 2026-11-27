"""Phase 10A — Agent #6 (`rel_`) 2-Phase Narrated Reel Script-to-Manifest Compiler.

Phase 1 (LLM / Mock Script Generation):
  - Generates `reelScript` with up to 11 scene kinds:
    `title, statement, bullets, term, compare, figure, chart, code, equation, plot, ready`
    plus graceful `fallback` for malformed scenes.
  - Supports beat cues (`rise`, `draw`, `count`, `pulse`) and grounded textbook `sourceFigureId`
    references from `rag.source_figures`.

Phase 2 (Deterministic Compiler + Safe AST Plot + Neutral TTSProvider + MinIO):
  - Reuses `validate_safe_math_expr` and `compile_plot_scene_spec` (`figure_validator.py`) with
    ZERO `eval()` to compile `plot` expressions into SVG `segments`, `tangents`, `areas`, `points`.
  - Verifies `sourceFigureId` strictly against `available_figures` allowlist (never trusts LLM URLs).
  - Synthesizes scene audio via `TTSProvider`, computes exact beat offsets (`startMs`/`endMs`)
    and word-level karaoke timings (`words[{text, startMs, endMs}]`).
  - Uploads audio clips into MinIO prefix `reels-audio/{courseId}/{lessonId}/v{contentVersion}/...`
    and returns `reelManifest` + `mediaCalls[]` (`mdc_`) with strictly ZERO quiz answer keys.
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.figure_validator import (
    compile_plot_scene_spec,
    validate_teach_media_and_figure,
)
from app.agents.providers import LLMProvider
from app.agents.tts_provider import TTSProvider, TtsSynthesisError, estimate_word_timings, get_tts_provider
from app.core.config import Settings, get_settings
from app.rag.storage import MemorySourceStorage, MinioSourceStorage, SourceStorageError, get_source_storage
from app.schemas.internal import FORBIDDEN_ANSWER_KEY_FIELDS, LlmUsageOut

logger = logging.getLogger(__name__)

ALLOWED_SCENE_KINDS = frozenset(
    {
        "title",
        "statement",
        "bullets",
        "term",
        "compare",
        "figure",
        "chart",
        "code",
        "equation",
        "plot",
        "ready",
        "fallback",
    }
)
ALLOWED_CUE_VERBS = frozenset({"rise", "draw", "count", "pulse"})
ALLOWED_CHART_TYPES = frozenset({"bar", "line", "donut"})
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass
class ReelCompilationResult:
    manifest: dict[str, Any]
    media_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: LlmUsageOut = field(default_factory=LlmUsageOut)
    reel_id: str = field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:16]}")


def _sanitize_id(raw: str, fallback: str) -> str:
    cleaned = _SAFE_ID_RE.sub("", (raw or "").strip())
    return cleaned[:48] or fallback


def _strip_forbidden_answer_keys(obj: Any) -> Any:
    """Defense-in-depth: ensure NO quiz answer key field ever enters `reelManifest`."""
    if isinstance(obj, list):
        return [_strip_forbidden_answer_keys(item) for item in obj]
    if isinstance(obj, dict):
        return {
            k: _strip_forbidden_answer_keys(v)
            for k, v in obj.items()
            if k not in FORBIDDEN_ANSWER_KEY_FIELDS
        }
    return obj


def _extract_teach_blocks(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = lesson.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict) and b.get("type") == "teach"]


def build_deterministic_reel_script(
    *,
    topic: str,
    lesson_title: str,
    lesson: dict[str, Any],
    language: str = "vi",
    available_figures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a rich deterministic Phase-1 Reel script covering key scenes at 0 cost (for Mock / fallback)."""
    teach_blocks = _extract_teach_blocks(lesson)
    first_teach = teach_blocks[0] if teach_blocks else {}
    paragraphs = first_teach.get("paragraphs") if isinstance(first_teach.get("paragraphs"), list) else []
    lead_paragraph = str(paragraphs[0]) if paragraphs else (
        f"Explore the core intuition and practical mechanics behind {lesson_title}."
        if language == "en"
        else f"Cùng nắm vững trực giác cốt lõi và cách vận dụng thực tế của {lesson_title}."
    )
    takeaway = str(first_teach.get("takeaway") or (
        f"Master the core pattern of {topic} before practicing."
        if language == "en"
        else f"Ghi nhớ quy luật nền tảng của {topic} trước khi làm bài tập."
    ))
    terms = first_teach.get("terms") if isinstance(first_teach.get("terms"), list) else []
    first_term = terms[0] if terms and isinstance(terms[0], dict) else None
    term_name = str(first_term.get("term") or topic) if first_term else topic
    term_def = str(
        first_term.get("definition")
        or (
            f"The central concept organizing how {topic} works in practice."
            if language == "en"
            else f"Khái niệm trung tâm định hình cách {topic} vận hành trong thực tế."
        )
    ) if first_term else (
        f"The central concept organizing how {topic} works in practice."
        if language == "en"
        else f"Khái niệm trung tâm định hình cách {topic} vận hành trong thực tế."
    )

    is_en = language == "en"
    scenes: list[dict[str, Any]] = [
        {
            "id": "sc_title",
            "kind": "title",
            "kicker": "LESSON REEL" if is_en else "TÓM TẮT AUDIOVISUAL",
            "title": lesson_title[:120],
            "subtitle": f"60-second visual intuition for {topic}" if is_en else f"Trực giác nhanh 60 giây về {topic}",
            "beats": [
                {
                    "say": (
                        f"Welcome to {lesson_title}. Let us build clear intuition for {topic} in under a minute."
                        if is_en
                        else f"Chào mừng bạn đến với {lesson_title}. Hãy nắm trực giác cốt lõi về {topic} trong chưa đầy một phút."
                    ),
                    "show": [{"verb": "rise", "target": "title"}],
                }
            ],
        },
        {
            "id": "sc_statement",
            "kind": "statement",
            "kicker": "CORE IDEA" if is_en else "Ý TƯỞNG CỐT LÕI",
            "statement": lead_paragraph[:220],
            "beats": [
                {
                    "say": lead_paragraph[:220],
                    "show": [{"verb": "pulse", "target": "statement"}],
                }
            ],
        },
        {
            "id": "sc_bullets",
            "kind": "bullets",
            "title": "Three steps to remember" if is_en else "Ba điểm mấu chốt cần nhớ",
            "bullets": (
                [
                    f"Identify the core mechanism of {topic}",
                    "Connect input conditions to observable output",
                    "Verify edge cases before applying at scale",
                ]
                if is_en
                else [
                    f"Xác định đúng cơ chế cốt lõi của {topic}",
                    "Liên kết điều kiện đầu vào với kết quả đầu ra",
                    "Kiểm chứng trường hợp biên trước khi áp dụng",
                ]
            ),
            "beats": [
                {
                    "say": (
                        f"First, identify the core mechanism of {topic}."
                        if is_en
                        else f"Đầu tiên, xác định đúng cơ chế cốt lõi của {topic}."
                    ),
                    "show": [{"verb": "rise", "target": "bullet-0"}],
                },
                {
                    "say": (
                        "Second, trace how inputs shape outputs and verify edge cases."
                        if is_en
                        else "Tiếp theo, theo dõi cách đầu vào tạo ra đầu ra và kiểm tra trường hợp biên."
                    ),
                    "show": [
                        {"verb": "rise", "target": "bullet-1"},
                        {"verb": "rise", "target": "bullet-2"},
                    ],
                },
            ],
        },
        {
            "id": "sc_term",
            "kind": "term",
            "term": term_name[:64],
            "definition": term_def[:200],
            "beats": [
                {
                    "say": (
                        f"Key term: {term_name}. {term_def[:140]}"
                        if is_en
                        else f"Thuật ngữ trọng tâm: {term_name}. {term_def[:140]}"
                    ),
                    "show": [{"verb": "pulse", "target": "term-card"}],
                }
            ],
        },
        {
            "id": "sc_compare",
            "kind": "compare",
            "title": "Intuition vs Common Pitfall" if is_en else "Cách làm chuẩn vs Lỗi thường gặp",
            "leftTitle": "Effective pattern" if is_en else "Cách làm hiệu quả",
            "leftPoints": (
                ["Check assumptions first", "Verify intermediate state"]
                if is_en
                else ["Kiểm tra giả thiết trước", "Đối chiếu trạng thái trung gian"]
            ),
            "rightTitle": "Common pitfall" if is_en else "Bẫy hay mắc",
            "rightPoints": (
                ["Skipping boundary checks", "Memorizing without structure"]
                if is_en
                else ["Bỏ qua kiểm tra biên", "Học vẹt thiếu liên kết"]
            ),
            "beats": [
                {
                    "say": (
                        "Compare the effective pattern on the left with the common pitfall on the right."
                        if is_en
                        else "So sánh cách làm hiệu quả bên trái với lỗi thường gặp bên phải."
                    ),
                    "show": [{"verb": "rise", "target": "compare-left"}, {"verb": "rise", "target": "compare-right"}],
                }
            ],
        },
    ]

    # Scene 6: Grounded figure from textbook (`sourceFigureId`) OR teach figure OR flow diagram
    first_fig_ref = available_figures[0] if available_figures else None
    teach_fig = first_teach.get("figure") if isinstance(first_teach.get("figure"), dict) else None
    if first_fig_ref and first_fig_ref.get("figureId"):
        scenes.append(
            {
                "id": "sc_figure",
                "kind": "figure",
                "title": str(first_fig_ref.get("caption") or f"Textbook figure: {topic}")[:100],
                "sourceFigureId": str(first_fig_ref["figureId"]),
                "beats": [
                    {
                        "say": (
                            f"Look at this verified textbook diagram illustrating {topic}."
                            if is_en
                            else f"Quan sát hình minh họa gốc từ giáo trình giải thích trực quan về {topic}."
                        ),
                        "show": [{"verb": "draw", "target": "figure"}],
                    }
                ],
            }
        )
    else:
        fig_payload = teach_fig if (teach_fig and not validate_teach_media_and_figure({"figure": teach_fig}, 0)) else {
            "kind": "diagram",
            "layout": "flow",
            "title": f"{topic} Pipeline",
            "nodes": [
                {"id": "n0", "label": "Input" if is_en else "Đầu vào"},
                {"id": "n1", "label": topic[:24]},
                {"id": "n2", "label": "Output" if is_en else "Kết quả"},
            ],
            "edges": [
                {"from": "n0", "to": "n1", "label": "parse" if is_en else "xử lý"},
                {"from": "n1", "to": "n2", "label": "verify" if is_en else "kiểm chứng"},
            ],
        }
        scenes.append(
            {
                "id": "sc_figure",
                "kind": "figure",
                "title": str(fig_payload.get("title") or f"{topic} Visual")[:100],
                "figure": fig_payload,
                "beats": [
                    {
                        "say": (
                            f"Follow the flow diagram showing how {topic} connects input to verified output."
                            if is_en
                            else f"Theo dõi sơ đồ luồng cho thấy cách {topic} kết nối đầu vào tới kết quả được kiểm chứng."
                        ),
                        "show": [{"verb": "draw", "target": "figure"}],
                    }
                ],
            }
        )

    # Scene 7: Chart (`bar`)
    scenes.append(
        {
            "id": "sc_chart",
            "kind": "chart",
            "title": "Mastery impact by study habit" if is_en else "Hiệu quả ghi nhớ theo phương pháp",
            "chart": {
                "chartType": "bar",
                "unit": "%",
                "series": [
                    {"label": "Passive" if is_en else "Đọc lướt", "value": 32},
                    {"label": "Active" if is_en else "Thực hành", "value": 74},
                    {"label": "Spaced" if is_en else "Ôn FSRS", "value": 92},
                ],
            },
            "beats": [
                {
                    "say": (
                        "Active recall and spaced repetition dramatically lift retention compared to passive reading."
                        if is_en
                        else "Chủ động thực hành kết hợp ôn tập ngắt quãng nâng tỷ lệ ghi nhớ vượt trội so với chỉ đọc lướt."
                    ),
                    "show": [{"verb": "count", "target": "chart-bars"}],
                }
            ],
        }
    )

    # Scene 8: Code snippet
    scenes.append(
        {
            "id": "sc_code",
            "kind": "code",
            "title": f"{topic} — Minimal Example" if is_en else f"{topic} — Ví dụ mã gọn",
            "language": "python",
            "code": (
                f"def evaluate_step(state: float, rate: float = 0.25) -> float:\n"
                f"    \"\"\"Core update rule for {topic[:32]}.\"\"\"\n"
                f"    delta = (1.0 - state) * rate\n"
                f"    return round(state + delta, 4)\n"
            ),
            "highlightLines": [3, 4],
            "beats": [
                {
                    "say": (
                        "In code, lines three and four compute the incremental update cleanly without side effects."
                        if is_en
                        else "Trong đoạn mã, dòng ba và dòng bốn tính bước cập nhật rõ ràng và dễ kiểm chứng."
                    ),
                    "show": [{"verb": "draw", "target": "code-lines"}],
                }
            ],
        }
    )

    # Scene 9: Equation (step-by-step KaTeX)
    scenes.append(
        {
            "id": "sc_equation",
            "kind": "equation",
            "title": "Step-by-step Formula" if is_en else "Công thức từng bước",
            "steps": [
                {"latex": r"f(x) = x^2 - 2x + 2", "note": "Base model" if is_en else "Hàm mục tiêu"},
                {"latex": r"f'(x) = 2x - 2 = 0 \implies x^* = 1", "note": "Critical point" if is_en else "Điểm cực tiểu"},
            ],
            "beats": [
                {
                    "say": (
                        "Start from the objective f of x equals x squared minus two x plus two."
                        if is_en
                        else "Bắt đầu từ hàm mục tiêu f x bằng x bình trừ hai x cộng hai."
                    ),
                    "show": [{"verb": "draw", "target": "eq-0"}],
                },
                {
                    "say": (
                        "Setting the derivative to zero locates the optimum at x equals one."
                        if is_en
                        else "Cho đạo hàm bằng không, ta tìm được điểm tối ưu tại x bằng một."
                    ),
                    "show": [{"verb": "rise", "target": "eq-1"}],
                },
            ],
        }
    )

    # Scene 10: Plot (safe AST compiled curve + tangent + area!)
    scenes.append(
        {
            "id": "sc_plot",
            "kind": "plot",
            "title": "Curve, Tangent & Area" if is_en else "Đồ thị, Tiếp tuyến & Diện tích",
            "plot": {
                "xRange": [-1, 4],
                "yRange": [-1, 6],
                "xLabel": "x",
                "yLabel": "f(x)",
                "functions": [{"expr": "x^2 - 2*x + 2", "label": "f(x) = x² - 2x + 2", "color": "#c85a27"}],
                "points": [{"x": 1, "y": 1, "label": "min (1, 1)"}],
                "tangents": [{"x": 2, "expr": "x^2 - 2*x + 2", "label": "f'(2) = 2"}],
                "areas": [{"fromX": 0, "toX": 2, "expr": "x^2 - 2*x + 2", "label": "∫₀² f(x)dx"}],
            },
            "beats": [
                {
                    "say": (
                        "On the plot, the curve reaches its minimum at one, the tangent at two has slope two, and the shaded area shows the integral."
                        if is_en
                        else "Trên đồ thị, đường cong đạt cực tiểu tại x bằng một, tiếp tuyến tại hai có hệ số góc hai, và vùng tô bóng biểu diễn tích phân."
                    ),
                    "show": [{"verb": "draw", "target": "plot-curves"}, {"verb": "pulse", "target": "plot-tangent"}],
                }
            ],
        }
    )

    # Scene 11: Ready CTA
    scenes.append(
        {
            "id": "sc_ready",
            "kind": "ready",
            "title": "Ready to practice?" if is_en else "Sẵn sàng thực hành?",
            "subtitle": takeaway[:180],
            "ctaLabel": "Start practice" if is_en else "Bắt đầu luyện tập",
            "beats": [
                {
                    "say": (
                        f"You now have the full picture of {lesson_title}. Let us test your understanding!"
                        if is_en
                        else f"Bạn đã nắm trọn bức tranh của {lesson_title}. Giờ hãy kiểm tra lại kiến thức qua các câu hỏi nhé!"
                    ),
                    "show": [{"verb": "pulse", "target": "ready-cta"}],
                }
            ],
        }
    )

    return {"styleVersion": "v1", "scenes": scenes}


def _normalize_cues(raw_cues: Any) -> list[dict[str, str]]:
    if not isinstance(raw_cues, list):
        return []
    out: list[dict[str, str]] = []
    for cue in raw_cues[:6]:
        if not isinstance(cue, dict):
            continue
        verb = str(cue.get("verb") or "rise").strip().lower()
        if verb not in ALLOWED_CUE_VERBS:
            verb = "rise"
        target = str(cue.get("target") or "stage").strip()[:64]
        if target:
            out.append({"verb": verb, "target": target})
    return out


def _compile_chart(raw_chart: Any) -> dict[str, Any] | None:
    if not isinstance(raw_chart, dict):
        return None
    ctype = str(raw_chart.get("chartType") or raw_chart.get("type") or "bar").strip().lower()
    if ctype not in ALLOWED_CHART_TYPES:
        ctype = "bar"
    raw_series = raw_chart.get("series") or raw_chart.get("items") or []
    if not isinstance(raw_series, list) or not raw_series:
        return None
    series: list[dict[str, Any]] = []
    for item in raw_series[:8]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:32]
        val = item.get("value")
        if label and isinstance(val, (int, float)) and not isinstance(val, bool):
            series.append({"label": label, "value": round(float(val), 2)})
    if not series:
        return None
    return {
        "chartType": ctype,
        "unit": str(raw_chart.get("unit") or "")[:16],
        "series": series,
    }


def _compile_scene_payload(
    raw_scene: dict[str, Any],
    *,
    scene_id: str,
    figures_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate and compile one scene's visual content; degrades gracefully to `fallback` if malformed."""
    raw_kind = str(raw_scene.get("kind") or "fallback").strip().lower()
    kind = raw_kind if raw_kind in ALLOWED_SCENE_KINDS else "fallback"

    out: dict[str, Any] = {
        "id": scene_id,
        "kind": kind,
    }
    if raw_scene.get("kicker"):
        out["kicker"] = str(raw_scene["kicker"]).strip()[:60]
    if raw_scene.get("title"):
        out["title"] = str(raw_scene["title"]).strip()[:140]
    if raw_scene.get("subtitle"):
        out["subtitle"] = str(raw_scene["subtitle"]).strip()[:240]

    if kind == "title":
        out["title"] = out.get("title") or "Lesson Overview"
    elif kind == "statement":
        stmt = str(raw_scene.get("statement") or out.get("subtitle") or out.get("title") or "").strip()
        if not stmt:
            out["kind"] = "fallback"
        else:
            out["statement"] = stmt[:320]
    elif kind == "bullets":
        raw_bullets = raw_scene.get("bullets") or []
        bullets = [str(b).strip()[:160] for b in raw_bullets if str(b).strip()][:5] if isinstance(raw_bullets, list) else []
        if not bullets:
            out["kind"] = "fallback"
        else:
            out["bullets"] = bullets
    elif kind == "term":
        term = str(raw_scene.get("term") or out.get("title") or "").strip()[:80]
        definition = str(raw_scene.get("definition") or out.get("subtitle") or "").strip()[:280]
        if not term or not definition:
            out["kind"] = "fallback"
        else:
            out["term"] = term
            out["definition"] = definition
    elif kind == "compare":
        left_pts = [str(p).strip()[:120] for p in (raw_scene.get("leftPoints") or []) if str(p).strip()][:4]
        right_pts = [str(p).strip()[:120] for p in (raw_scene.get("rightPoints") or []) if str(p).strip()][:4]
        if not left_pts and not right_pts:
            out["kind"] = "fallback"
        else:
            out["leftTitle"] = str(raw_scene.get("leftTitle") or "A")[:60]
            out["rightTitle"] = str(raw_scene.get("rightTitle") or "B")[:60]
            out["leftPoints"] = left_pts
            out["rightPoints"] = right_pts
    elif kind == "figure":
        raw_sfid = str(raw_scene.get("sourceFigureId") or "").strip()
        resolved_spec = figures_by_id.get(raw_sfid) if raw_sfid else None
        if resolved_spec is not None:
            src_id = str(resolved_spec.get("sourceId") or "")
            fig_id = str(resolved_spec.get("figureId") or raw_sfid)
            out["sourceFigureId"] = fig_id
            out["image"] = {
                "url": f"/v1/library/figures/{src_id}/{fig_id}",
                "alt": str(resolved_spec.get("caption") or out.get("title") or "Textbook figure")[:180],
                "caption": str(resolved_spec.get("caption") or "")[:240],
                "sourceTitle": str(resolved_spec.get("sourceTitle") or "")[:140],
                "attribution": str(resolved_spec.get("attribution") or "")[:200],
            }
        elif isinstance(raw_scene.get("figure"), dict):
            fig_copy = copy.deepcopy(raw_scene["figure"])
            errs = validate_teach_media_and_figure({"figure": fig_copy}, 0)
            if not errs:
                out["figure"] = fig_copy
            else:
                out["kind"] = "fallback"
                out["fallbackReason"] = "invalid_figure"
        else:
            out["kind"] = "fallback"
            out["fallbackReason"] = "unverified_source_figure"
    elif kind == "chart":
        compiled_chart = _compile_chart(raw_scene.get("chart"))
        if compiled_chart is None:
            out["kind"] = "fallback"
        else:
            out["chart"] = compiled_chart
    elif kind == "code":
        code = str(raw_scene.get("code") or "")
        if not code.strip() or len(code) > 4000:
            out["kind"] = "fallback"
        else:
            out["code"] = code
            out["language"] = str(raw_scene.get("language") or "text").strip()[:32]
            hl = raw_scene.get("highlightLines")
            if isinstance(hl, list):
                out["highlightLines"] = [int(n) for n in hl if isinstance(n, int) and not isinstance(n, bool) and n >= 1][:12]
            else:
                out["highlightLines"] = []
    elif kind == "equation":
        raw_steps = raw_scene.get("steps") or []
        steps: list[dict[str, str]] = []
        if isinstance(raw_steps, list):
            for st in raw_steps[:6]:
                if isinstance(st, dict) and str(st.get("latex") or "").strip():
                    steps.append(
                        {
                            "latex": str(st["latex"]).strip()[:320],
                            "note": str(st.get("note") or "").strip()[:120],
                        }
                    )
                elif isinstance(st, str) and st.strip():
                    steps.append({"latex": st.strip()[:320], "note": ""})
        if not steps and raw_scene.get("latex"):
            steps.append({"latex": str(raw_scene["latex"]).strip()[:320], "note": ""})
        if not steps:
            out["kind"] = "fallback"
        else:
            out["steps"] = steps
    elif kind == "plot":
        raw_plot = raw_scene.get("plot") if isinstance(raw_scene.get("plot"), dict) else raw_scene
        compiled_plot = compile_plot_scene_spec(raw_plot)
        if not compiled_plot["curves"]:
            out["kind"] = "fallback"
            out["fallbackReason"] = "invalid_plot_expression"
        else:
            out["plot"] = compiled_plot
    elif kind == "ready":
        out["ctaLabel"] = str(raw_scene.get("ctaLabel") or "Start practice")[:60]

    if out["kind"] == "fallback":
        out.setdefault("title", out.get("title") or "Summary")
        out.setdefault("statement", out.get("subtitle") or out.get("title") or "Key concept summary")
    return out


async def compile_lesson_reel(
    *,
    course_id: str,
    lesson_id: str,
    content_version: int,
    topic: str,
    lesson_title: str,
    lesson: dict[str, Any],
    language: str = "vi",
    available_figures: list[dict[str, Any]] | None = None,
    provider: LLMProvider | None = None,
    tts_provider: TTSProvider | None = None,
    storage: MemorySourceStorage | MinioSourceStorage | None = None,
    settings: Settings | None = None,
    prebuilt_script: dict[str, Any] | None = None,
) -> ReelCompilationResult:
    """Execute the complete 2-Phase Narrated Reel pipeline (Script -> AST/TTS/MinIO -> Manifest)."""
    cfg = settings or get_settings()
    tts = tts_provider or get_tts_provider(cfg)
    store = storage or get_source_storage(cfg)

    figures_by_id: dict[str, dict[str, Any]] = {}
    for fig in available_figures or []:
        if isinstance(fig, dict) and fig.get("figureId") and fig.get("sourceId"):
            figures_by_id[str(fig["figureId"]).strip()] = fig

    # Phase 1: Obtain `reelScript` (from LLM Agent #6 when configured, else deterministic clean-room script)
    usage = LlmUsageOut(provider="mock", model="mock-reel-v1")
    script = prebuilt_script
    if script is None:
        llm_fn = getattr(provider, "generate_reel_script", None) if provider is not None else None
        if callable(llm_fn):
            try:
                script, usage = await llm_fn(
                    topic=topic,
                    lesson_title=lesson_title,
                    teach_blocks=_extract_teach_blocks(lesson),
                    language=language,
                    available_figures=list(figures_by_id.values()),
                )
            except Exception as exc:  # noqa: BLE001 — degrade gracefully to deterministic script
                logger.warning("reel_script_llm_fallback error_type=%s", type(exc).__name__)
                script = None

    if not isinstance(script, dict) or not isinstance(script.get("scenes"), list) or not script["scenes"]:
        script = build_deterministic_reel_script(
            topic=topic,
            lesson_title=lesson_title,
            lesson=lesson,
            language=language,
            available_figures=list(figures_by_id.values()),
        )

    reel_id = f"rel_{uuid.uuid4().hex[:16]}"
    safe_course_id = _sanitize_id(course_id, "crs_unknown")
    safe_lesson_id = _sanitize_id(lesson_id, "lsn_unknown")
    safe_ver = max(1, int(content_version))
    style_version = str(script.get("styleVersion") or "v1")[:32]

    compiled_scenes: list[dict[str, Any]] = []
    media_calls: list[dict[str, Any]] = []
    total_duration_ms = 0

    # Phase 2: Deterministic compile + safe AST plot + TTS audio upload to `reels-audio/...`
    for idx, raw_scene in enumerate(script["scenes"][:11]):
        if not isinstance(raw_scene, dict):
            continue
        scene_id = _sanitize_id(str(raw_scene.get("id") or f"sc_{idx + 1}"), f"sc_{idx + 1}")
        compiled_scene = _compile_scene_payload(
            raw_scene,
            scene_id=scene_id,
            figures_by_id=figures_by_id,
        )

        raw_beats = raw_scene.get("beats") if isinstance(raw_scene.get("beats"), list) else []
        clean_beats: list[dict[str, Any]] = []
        for b in raw_beats[:6]:
            if isinstance(b, dict) and str(b.get("say") or "").strip():
                clean_beats.append(
                    {
                        "say": str(b["say"]).strip()[:500],
                        "cues": _normalize_cues(b.get("show") or b.get("cues")),
                    }
                )
        if not clean_beats:
            fallback_say = str(
                compiled_scene.get("statement")
                or compiled_scene.get("subtitle")
                or compiled_scene.get("title")
                or lesson_title
            )[:240]
            clean_beats = [{"say": fallback_say, "cues": [{"verb": "rise", "target": "stage"}]}]

        full_narration = " ".join(b["say"] for b in clean_beats)
        audio_info: dict[str, Any] | None = None
        words_out: list[dict[str, Any]] = []
        scene_duration_ms = 0

        try:
            tts_res = await tts.synthesize(full_narration, language=language)
            scene_duration_ms = tts_res.duration_ms
            words_out = [w.to_dict() for w in tts_res.words]
            clip_filename = f"v{safe_ver}_{scene_id}.{tts_res.file_ext}"
            object_key = f"reels-audio/{safe_course_id}/{safe_lesson_id}/{clip_filename}"
            await store.put_bytes_async(object_key, tts_res.audio_bytes, content_type=tts_res.content_type)
            audio_info = {
                "clipId": clip_filename,
                "url": f"/v1/lessons/{lesson_id}/reel/audio/{clip_filename}",
                "contentType": tts_res.content_type,
                "durationMs": scene_duration_ms,
                "provider": tts_res.provider,
                "voice": tts_res.voice,
            }
            media_calls.append(
                {
                    "id": f"mdc_{uuid.uuid4().hex[:16]}",
                    "kind": "reel_tts",
                    "sceneId": scene_id,
                    "clipId": clip_filename,
                    "provider": tts_res.provider,
                    "voice": tts_res.voice,
                    "objectKey": object_key,
                    "contentType": tts_res.content_type,
                    "byteSize": len(tts_res.audio_bytes),
                    "durationMs": scene_duration_ms,
                    "status": "ready",
                }
            )
        except (TtsSynthesisError, SourceStorageError) as exc:
            # Degrade gracefully to silent caption-timed playback if TTS/storage transiently fails
            logger.warning("reel_tts_silent_fallback scene=%s error_type=%s", scene_id, type(exc).__name__)
            est_words, scene_duration_ms = estimate_word_timings(full_narration)
            words_out = [w.to_dict() for w in est_words]
            audio_info = None

        # Partition beat startMs/endMs proportionally across scene_duration_ms
        beat_weights = [max(1, len(b["say"])) for b in clean_beats]
        weight_total = sum(beat_weights)
        beat_cursor = 0
        compiled_beats: list[dict[str, Any]] = []
        for b_idx, (b, bw) in enumerate(zip(clean_beats, beat_weights, strict=True)):
            span = (
                scene_duration_ms - beat_cursor
                if b_idx == len(clean_beats) - 1
                else int(round(scene_duration_ms * (bw / weight_total)))
            )
            end_ms = min(scene_duration_ms, beat_cursor + max(250, span))
            compiled_beats.append(
                {
                    "index": b_idx,
                    "say": b["say"],
                    "startMs": beat_cursor,
                    "endMs": end_ms,
                    "cues": b["cues"],
                }
            )
            beat_cursor = end_ms

        compiled_scene["durationMs"] = scene_duration_ms
        compiled_scene["audio"] = audio_info
        compiled_scene["words"] = words_out
        compiled_scene["beats"] = compiled_beats
        compiled_scenes.append(compiled_scene)
        total_duration_ms += scene_duration_ms

    manifest = _strip_forbidden_answer_keys(
        {
            "id": reel_id,
            "version": 1,
            "contentVersion": safe_ver,
            "styleVersion": style_version,
            "language": language,
            "durationMs": total_duration_ms,
            "scenes": compiled_scenes,
        }
    )

    return ReelCompilationResult(
        manifest=manifest,
        media_calls=media_calls,
        usage=usage,
        reel_id=reel_id,
    )
