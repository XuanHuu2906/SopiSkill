"""Test helpers — dựng đáp án từ **private content trong DB**.

Quan trọng: test E2E/HTTP không được đọc answer key từ public payload (public
payload cố tình không có key). Vì vậy helper này đọc `lessons.content` trực tiếp
từ DB (server-side, giống grading service) rồi tính câu trả lời đúng.
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Lesson
from app.services.lesson_content import public_block


async def load_private_blocks(lesson_id_prefixed: str) -> tuple[uuid.UUID, int, list[dict]]:
    raw = lesson_id_prefixed.removeprefix("lsn_")
    lid = uuid.UUID(raw)
    async with SessionLocal() as db:
        lesson = (
            await db.execute(select(Lesson).where(Lesson.id == lid))
        ).scalar_one()
        return lesson.id, lesson.content_version, list(lesson.content or [])


async def correct_answers(lesson_id_prefixed: str) -> tuple[int, list[dict]]:
    """Trả (contentVersion, answers đúng hoàn toàn) dựa trên private content."""
    lid, version, blocks = await load_private_blocks(lesson_id_prefixed)
    answers: list[dict] = []
    for idx, block in enumerate(blocks):
        btype = block.get("type")
        if btype == "teach":
            continue
        if btype == "mc":
            answers.append({"index": idx, "answer": int(block["answerIndex"])})
        elif btype == "blank":
            answers.append({"index": idx, "answer": block["answer"]})
        elif btype == "short":
            answers.append({"index": idx, "answer": block["acceptedAnswers"][0]})
        elif btype == "order":
            pub = public_block(lid, version, idx, block)
            text_to_id = {item["text"]: item["id"] for item in pub["items"]}
            answers.append(
                {"index": idx, "answer": [text_to_id[text] for text in block["items"]]}
            )
        elif btype == "match":
            pub = public_block(lid, version, idx, block)
            left_ids = {item["text"]: item["id"] for item in pub["lefts"]}
            right_ids = {item["text"]: item["id"] for item in pub["rights"]}
            answers.append(
                {
                    "index": idx,
                    "answer": {
                        left_ids[left]: right_ids[right] for left, right in block["pairs"]
                    },
                }
            )
        else:
            answers.append({"index": idx, "answer": None})
    return version, answers


def wrong_answers(blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for idx, block in enumerate(blocks):
        if block.get("type") == "teach":
            continue
        out.append({"index": idx, "answer": "zzz-sai-chac-chan"})
    return out
