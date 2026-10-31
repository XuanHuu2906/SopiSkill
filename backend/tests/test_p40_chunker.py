"""P4.0 chunker unit tests — không phụ thuộc font PDF hay DB."""

from app.services import ingest


def test_chunker_handles_vietnamese_text_and_headings():
    page_text = (
        "Chương 1: Tổng quan\n"
        + "Python là ngôn ngữ lập trình bậc cao. " * 40
        + "\n\n"
        + "1.1 Cài đặt\n"
        + "Cài Python từ trang chủ. " * 30
    )
    pages = [ingest.ExtractedPage(page_number=1, text=page_text)]
    drafts = ingest.chunk_pages(pages, target_chars=400, min_chars=100)
    assert drafts
    assert all(d.page_number == 1 for d in drafts)
    for draft in drafts:
        assert page_text[draft.char_start : draft.char_end] == draft.text
        assert draft.section_anchor
    starts = [d.char_start for d in drafts]
    assert starts == sorted(starts)
    for previous, current in zip(drafts, drafts[1:]):
        assert current.char_start >= previous.char_end


def test_chunker_splits_long_single_block():
    page_text = " ".join(["token"] * 2000) + "\n"
    pages = [ingest.ExtractedPage(page_number=4, text=page_text)]
    drafts = ingest.chunk_pages(pages, target_chars=500, min_chars=100)
    assert len(drafts) > 1
    assert all(d.page_number == 4 for d in drafts)
    assert all(len(d.text) <= 1100 for d in drafts)
    for draft in drafts:
        assert page_text[draft.char_start : draft.char_end] == draft.text
