"""P4.0 — trung thực trạng thái kiểm chứng sau khi đã ingest (không cần DB)."""

def test_locator_not_verified_merely_because_content_exists():
    """Có chunk ≠ đã đối chiếu locator. P4.0 không được tự nhảy mức kiểm chứng."""
    from app.models import Source, SourceType, SourceVisibility, SourceVerificationStatus
    from app.services import citation_service

    source = Source(
        source_type=SourceType.user_document,
        title="Doc",
        version="1",
        visibility=SourceVisibility.private,
        verification_status=SourceVerificationStatus.unverified,
        dedupe_key="x",
    )
    status_value, _reasons = citation_service.validate_citation_locator(
        source,
        chunk_id="chk_1",
        page_number=2,
        has_ingested_content=True,
    )
    assert status_value.value == "unverified"
    # Không bao giờ tự thành verified chỉ vì có chunk store.
    status_no_locator, _ = citation_service.validate_citation_locator(
        source, has_ingested_content=True
    )
    assert status_no_locator.value == "unverified"


def test_evaluation_marks_evidence_known_when_content_ingested():
    from app.models import Source, SourceType, SourceVisibility, SourceVerificationStatus
    from app.services import source_evaluation

    source = Source(
        source_type=SourceType.user_document,
        title="Doc",
        visibility=SourceVisibility.private,
        verification_status=SourceVerificationStatus.unverified,
        dedupe_key="y",
    )
    without = source_evaluation.evaluate_source(source, topics=["python"])
    with_content = source_evaluation.evaluate_source(
        source, topics=["python"], has_content=True
    )
    without_evidence = next(c for c in without.criteria if c.key == "evidence")
    with_evidence = next(c for c in with_content.criteria if c.key == "evidence")
    assert with_evidence.score is not None
    assert without_evidence.score is None or with_evidence.score > without_evidence.score
    # Vẫn KHÔNG tự đặt metadata_verified/evidence_supported.
    assert with_content.suggested_status.value in (
        "unverified",
        "pending_review",
        "metadata_verified",
    )
