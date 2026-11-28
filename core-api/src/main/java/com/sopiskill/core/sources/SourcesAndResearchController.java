package com.sopiskill.core.sources;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
public class SourcesAndResearchController {

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final SopiProperties props;
    private final AiEngineClient aiEngine;
    private final S3PresignService s3Presign;

    public SourcesAndResearchController(
            JdbcClient jdbc,
            JsonHelper json,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            SopiProperties props,
            AiEngineClient aiEngine,
            S3PresignService s3Presign
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.props = props;
        this.aiEngine = aiEngine;
        this.s3Presign = s3Presign;
    }

    public record PresignUploadRequest(
            @NotBlank String filename,
            String contentType,
            Long byteSize,
            String title
    ) {}

    public record TriggerIngestRequest(String documentId, String rawText, Boolean ocrEnabled) {}

    public record CreateSourceRequest(
            @NotBlank String title,
            String sourceType,
            String visibility,
            String canonicalUrl,
            String author,
            String publisher,
            String language,
            String version
    ) {}

    public record LinkSourceRequest(@NotBlank String sourceId) {}

    public record SearchSourcesRequest(@NotBlank String query, List<String> sourceIds) {}

    public record WebDocumentRequest(String url, String arxivId, Boolean userConfirmedRights) {}

    public record ResearchRequest(Integer maxSources, String learningGoals, String learnerLevel) {}

    private static final java.util.regex.Pattern SAFE_FIGURE_ID =
            java.util.regex.Pattern.compile("^[a-zA-Z0-9_-]{1,64}$");
    private static final java.util.Set<String> ALLOWED_FIGURE_MIME = java.util.Set.of(
            "image/webp", "image/png", "image/jpeg", "image/gif", "image/svg+xml"
    );

    @GetMapping("/v1/library/figures/{sourceId}/{figureId}")
    public ResponseEntity<byte[]> getLibraryFigure(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @PathVariable String figureId,
            HttpServletRequest request
    ) {
        rateLimiter.check(request, "library_figure", 240, 60);
        if (!SAFE_FIGURE_ID.matcher(figureId).matches()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_FIGURE_ID", "Mã hình minh họa không hợp lệ.");
        }
        UUID srcUuid = IdCodec.parse(sourceId, "src");
        var row = jdbc.sql("""
                        SELECT owner_id, visibility
                        FROM core.sources
                        WHERE id = :id
                        """)
                .param("id", srcUuid)
                .query((rs, rowNum) -> Map.of(
                        "ownerId", rs.getObject("owner_id") == null ? "" : rs.getObject("owner_id").toString(),
                        "visibility", rs.getString("visibility") == null ? "private" : rs.getString("visibility")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "SOURCE_NOT_FOUND", "Không tìm thấy nguồn tài liệu."));

        boolean isPublic = "public".equalsIgnoreCase(row.get("visibility"));
        boolean isOwner = principal != null && principal.userId().toString().equals(row.get("ownerId"));
        if (!isPublic && !isOwner) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "Bạn không có quyền truy cập hình minh họa của nguồn này.");
        }

        String ownerParam = principal != null ? IdCodec.format("usr", principal.userId()) : "";
        String internalPath = "/internal/library/figures/" + sourceId + "/" + figureId
                + (ownerParam.isBlank() ? "" : "?ownerId=" + java.net.URLEncoder.encode(ownerParam, java.nio.charset.StandardCharsets.UTF_8));
        var upstream = aiEngine.getBinary(internalPath, "fig_" + figureId);
        if (upstream.statusCode() == 404) {
            throw new ApiException(HttpStatus.NOT_FOUND, "FIGURE_NOT_FOUND", "Không tìm thấy hình minh họa.");
        }
        if (upstream.statusCode() < 200 || upstream.statusCode() >= 300) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "FIGURE_UPSTREAM_ERROR", "Không thể tải hình minh họa.");
        }

        String rawType = upstream.headers().firstValue("content-type").orElse("image/webp").split(";")[0].trim().toLowerCase();
        String safeType = ALLOWED_FIGURE_MIME.contains(rawType) ? rawType : "application/octet-stream";

        return ResponseEntity.ok()
                .header("Content-Type", safeType)
                .header("Cache-Control", "public, max-age=86400")
                .header("X-Content-Type-Options", "nosniff")
                .body(upstream.body());
    }

    @GetMapping("/v1/sources/ingest-config")
    public Map<String, Object> ingestConfig() {
        Map<String, Object> cfg = new LinkedHashMap<>();
        cfg.put("ingestEnabled", true);
        cfg.put("storageConfigured", true);
        cfg.put("maxPdfBytes", 25 * 1024 * 1024);
        cfg.put("maxPdfPages", 200);
        cfg.put("pipelineVersion", "pypdf-v1");
        cfg.put("embeddingEnabled", true);
        cfg.put("embeddingConfigured", true);
        cfg.put("embeddingProvider", "hashing");
        cfg.put("embeddingModel", "hashing-ngram-v1");
        cfg.put("embeddingDimension", 256);
        cfg.put("ragEnabled", props.ragEnabled());
        cfg.put("webEnabled", false);
        cfg.put("webAllowedHostCount", 0);
        cfg.put("webMaxFetchBytes", 10 * 1024 * 1024);
        cfg.put("webRespectRobots", true);
        cfg.put("arxivEnabled", false);
        cfg.put("ocrEnabled", false);
        cfg.put("ocrConfigured", false);
        cfg.put("ocrEngine", "vietocr");
        cfg.put("ocrVersion", null);
        cfg.put("ocrMaxPages", 30);
        cfg.put("ocrDpi", 200);
        return cfg;
    }

    @GetMapping("/v1/sources")
    public Map<String, Object> listSources(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        int safeOffset = Math.max(0, offset);
        UUID uid = principal.userId();

        int total = jdbc.sql("SELECT COUNT(*) FROM core.sources WHERE owner_id = :uid OR visibility = 'public'")
                .param("uid", uid).query(Integer.class).single();

        List<Map<String, Object>> items = jdbc.sql("""
                SELECT id, source_type, title, canonical_url, author, publisher, publication_date,
                       source_updated_at, retrieved_at, language, version, visibility, license_info,
                       content_hash, verification_status, owner_id, created_at,
                       brief, word_count, duration_minutes, suggested_topic, reject_reason,
                       external_key, domain_slug, pedagogy_tier, commercial_safe, isbn, doi
                FROM core.sources
                WHERE owner_id = :uid OR visibility = 'public'
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """)
                .param("uid", uid)
                .param("limit", safeLimit)
                .param("offset", safeOffset)
                .query(this::mapSourceRow)
                .list();

        return Map.of(
                "items", items,
                "total", total,
                "limit", safeLimit,
                "offset", safeOffset,
                "hasMore", safeOffset + items.size() < total
        );
    }

    @GetMapping("/v1/sources/discover")
    public Map<String, Object> discoverSources(
            @RequestParam(defaultValue = "") String q,
            @RequestParam(required = false) String domain,
            @RequestParam(defaultValue = "beginner") String level,
            @RequestParam(defaultValue = "practical") String depth,
            @RequestParam(defaultValue = "10") int limit
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 30));
        List<Map<String, Object>> ranked = rankPublicLibrarySources(q, domain, level, depth, safeLimit);
        return Map.of("query", q, "items", ranked, "total", ranked.size());
    }

    @PostMapping("/v1/sources")
    @Transactional
    public ResponseEntity<Map<String, Object>> createSource(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody CreateSourceRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "source_create", 30, 60);
        UUID sid = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.sources (
                    id, owner_id, source_type, title, canonical_url, author, publisher, language, version, visibility
                ) VALUES (
                    :id, :uid, :stype, :title, :url, :author, :publisher, :lang, :ver, :vis
                )
                """)
                .param("id", sid)
                .param("uid", principal.userId())
                .param("stype", body.sourceType() == null ? "user_document" : body.sourceType())
                .param("title", body.title().trim())
                .param("url", body.canonicalUrl())
                .param("author", body.author())
                .param("publisher", body.publisher())
                .param("lang", body.language())
                .param("ver", body.version())
                .param("vis", "private")
                .update();

        return ResponseEntity.status(HttpStatus.CREATED).body(loadOwnedOrPublicSource(principal.userId(), sid));
    }

    @PostMapping("/v1/sources/upload")
    @Transactional
    public ResponseEntity<Map<String, Object>> presignPdfUpload(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody PresignUploadRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "source_presign", 20, 60);

        long maxBytes = 25L * 1024 * 1024;
        long size = body.byteSize() == null ? 0L : body.byteSize();
        if (size <= 0 || size > maxBytes) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "PDF_SIZE_INVALID", "Dung lượng PDF phải lớn hơn 0 và không vượt quá 25 MB.");
        }
        String ct = body.contentType() == null ? "application/pdf" : body.contentType().trim().toLowerCase();
        if (!"application/pdf".equals(ct)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "PDF_CONTENT_TYPE_INVALID", "Chỉ hỗ trợ tệp PDF (application/pdf).");
        }

        UUID sid = UUID.randomUUID();
        UUID did = UUID.randomUUID();
        String cleanFilename = body.filename().trim().replaceAll("[^a-zA-Z0-9._-]", "_");
        String title = (body.title() != null && !body.title().isBlank())
                ? body.title().trim()
                : cleanFilename.replaceAll("(?i)\\.pdf$", "").replace('_', ' ');
        String storageKey = "sources/" + sid + "/" + did + ".pdf";

        jdbc.sql("""
                INSERT INTO core.sources (id, owner_id, source_type, title, visibility)
                VALUES (:sid, :uid, 'user_document', :title, 'private')
                """)
                .param("sid", sid)
                .param("uid", principal.userId())
                .param("title", title.isBlank() ? "Tài liệu PDF" : title)
                .update();

        jdbc.sql("""
                INSERT INTO core.source_documents (
                    id, source_id, status, origin, mime, byte_size, original_filename, storage_key
                ) VALUES (
                    :did, :sid, 'queued', 'upload', 'application/pdf', :size, :fname, :skey
                )
                """)
                .param("did", did)
                .param("sid", sid)
                .param("size", size)
                .param("fname", cleanFilename)
                .param("skey", storageKey)
                .update();

        int expires = 900;
        String uploadUrl = s3Presign.createPresignedPutUrl(storageKey, expires);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("sourceId", IdCodec.format("src", sid));
        out.put("documentId", IdCodec.format("doc", did));
        out.put("storageKey", storageKey);
        out.put("uploadUrl", uploadUrl);
        out.put("method", "PUT");
        out.put("expiresInSeconds", expires);
        return ResponseEntity.status(HttpStatus.CREATED).body(out);
    }

    @PostMapping("/v1/sources/{sourceId}/ingest")
    @Transactional
    public ResponseEntity<Map<String, Object>> triggerSourceIngest(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @RequestBody(required = false) TriggerIngestRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "source_ingest", 20, 60);
        UUID sid = IdCodec.parse(sourceId, "src");
        loadOwnedSource(principal.userId(), sid);

        String sourceTitle = jdbc.sql("SELECT title FROM core.sources WHERE id = :sid")
                .param("sid", sid).query(String.class).single();

        UUID docUuid;
        String storageKey;
        if (body != null && body.documentId() != null && !body.documentId().isBlank()) {
            docUuid = IdCodec.parse(body.documentId(), "doc");
            storageKey = jdbc.sql("SELECT storage_key FROM core.source_documents WHERE id = :did AND source_id = :sid")
                    .param("did", docUuid).param("sid", sid).query(String.class).optional().orElse(null);
        } else {
            var latestDoc = jdbc.sql("""
                    SELECT id, storage_key FROM core.source_documents
                    WHERE source_id = :sid ORDER BY created_at DESC LIMIT 1
                    """)
                    .param("sid", sid)
                    .query((rs, rowNum) -> Map.of(
                            "id", rs.getObject("id", UUID.class),
                            "storageKey", rs.getString("storage_key") == null ? "" : rs.getString("storage_key")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Chưa có tệp nào cho nguồn này."));
            docUuid = (UUID) latestDoc.get("id");
            storageKey = String.valueOf(latestDoc.get("storageKey"));
        }

        jdbc.sql("UPDATE core.source_documents SET status = 'extracting' WHERE id = :did")
                .param("did", docUuid).update();

        boolean useRawText = body != null && body.rawText() != null && !body.rawText().isBlank();
        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("sourceId", IdCodec.format("src", sid));
        msg.put("documentId", IdCodec.format("doc", docUuid));
        msg.put("idempotencyKey", "ing_" + docUuid + "_" + System.currentTimeMillis());
        msg.put("ownerId", IdCodec.format("usr", principal.userId()));
        msg.put("sourceTitle", sourceTitle);
        msg.put("sourceKind", useRawText ? "raw_text" : "pdf_s3");
        if (useRawText) {
            msg.put("rawText", body.rawText());
        } else {
            msg.put("storageKey", storageKey);
        }
        msg.put("ocrEnabled", body != null && Boolean.TRUE.equals(body.ocrEnabled()));
        msg.put("correlationId", "cor_" + docUuid.toString().replace("-", "").substring(0, 16));

        aiEngine.enqueueIngestJob(msg);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(Map.of(
                "sourceId", IdCodec.format("src", sid),
                "documentId", IdCodec.format("doc", docUuid),
                "status", "extracting"
        ));
    }

    @GetMapping("/v1/sources/{sourceId}")
    public Map<String, Object> getSource(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId
    ) {
        return loadOwnedOrPublicSource(principal.userId(), IdCodec.parse(sourceId, "src"));
    }

    @GetMapping("/v1/sources/{sourceId}/evaluation")
    public Map<String, Object> getSourceEvaluation(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId
    ) {
        UUID sid = IdCodec.parse(sourceId, "src");
        loadOwnedOrPublicSource(principal.userId(), sid);
        return Map.of("sourceId", IdCodec.format("src", sid), "status", "unverified", "checks", List.of());
    }

    @DeleteMapping("/v1/sources/{sourceId}")
    @Transactional
    public ResponseEntity<Void> deleteSource(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID sid = IdCodec.parse(sourceId, "src");
        int deleted = jdbc.sql("DELETE FROM core.sources WHERE id = :sid AND owner_id = :uid")
                .param("sid", sid).param("uid", principal.userId()).update();
        if (deleted == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "SOURCE_NOT_FOUND", "Không tìm thấy tài liệu nguồn.");
        }
        aiEngine.deleteRagResourceBestEffort("/internal/rag/sources/" + IdCodec.format("src", sid), null);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/v1/sources/{sourceId}/documents")
    public Map<String, Object> listSourceDocuments(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId
    ) {
        UUID sid = IdCodec.parse(sourceId, "src");
        loadOwnedOrPublicSource(principal.userId(), sid);

        List<Map<String, Object>> docs = jdbc.sql("""
                SELECT id, source_id, status, origin, origin_url, mime, byte_size, page_count,
                       pipeline_version, original_filename, chunk_count, preview, error_json,
                       attempts, rights_confirmed, text_source, ocr_pages, ocr_engine, ocr_version,
                       ingested_at, created_at
                FROM core.source_documents
                WHERE source_id = :sid
                ORDER BY created_at DESC
                """)
                .param("sid", sid)
                .query(this::mapDocumentRow)
                .list();

        boolean ingested = docs.stream().anyMatch(d -> "ready".equals(d.get("status")));
        return Map.of(
                "sourceId", IdCodec.format("src", sid),
                "items", docs,
                "total", docs.size(),
                "contentIngested", ingested,
                "notice", ingested ? "" : "Chưa có tài liệu nào được trích xuất hoàn tất."
        );
    }

    @GetMapping("/v1/sources/{sourceId}/documents/{documentId}")
    public Map<String, Object> getSourceDocument(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @PathVariable String documentId
    ) {
        UUID sid = IdCodec.parse(sourceId, "src");
        UUID did = IdCodec.parse(documentId, "doc");
        loadOwnedOrPublicSource(principal.userId(), sid);
        return jdbc.sql("""
                SELECT id, source_id, status, origin, origin_url, mime, byte_size, page_count,
                       pipeline_version, original_filename, chunk_count, preview, error_json,
                       attempts, rights_confirmed, text_source, ocr_pages, ocr_engine, ocr_version,
                       ingested_at, created_at
                FROM core.source_documents
                WHERE id = :did AND source_id = :sid
                """)
                .param("did", did)
                .param("sid", sid)
                .query(this::mapDocumentRow)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Không tìm thấy tài liệu."));
    }

    @PostMapping("/v1/sources/{sourceId}/document")
    @Transactional
    public ResponseEntity<Map<String, Object>> uploadSourceDocument(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @RequestParam("file") MultipartFile file,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "source_upload", 20, 60);
        UUID sid = IdCodec.parse(sourceId, "src");
        loadOwnedSource(principal.userId(), sid);

        UUID docId = UUID.randomUUID();
        String storageKey = "sources/" + sid + "/" + docId + ".pdf";
        jdbc.sql("""
                INSERT INTO core.source_documents (
                    id, source_id, status, origin, mime, byte_size, original_filename, storage_key
                ) VALUES (
                    :did, :sid, 'queued', 'upload', :mime, :size, :fname, :skey
                )
                """)
                .param("did", docId)
                .param("sid", sid)
                .param("mime", file.getContentType() == null ? "application/pdf" : file.getContentType())
                .param("size", file.getSize())
                .param("fname", file.getOriginalFilename())
                .param("skey", storageKey)
                .update();

        return ResponseEntity.status(HttpStatus.ACCEPTED).body(getSourceDocument(principal, sourceId, IdCodec.format("doc", docId)));
    }

    @PostMapping("/v1/sources/{sourceId}/web-document")
    @Transactional
    public ResponseEntity<Map<String, Object>> ingestWebDocument(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @RequestBody WebDocumentRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        if (!Boolean.TRUE.equals(body.userConfirmedRights())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "RIGHTS_CONFIRMATION_REQUIRED", "Cần xác nhận quyền sử dụng tài liệu.");
        }
        UUID sid = IdCodec.parse(sourceId, "src");
        loadOwnedSource(principal.userId(), sid);

        UUID docId = UUID.randomUUID();
        String origin = (body.arxivId() != null && !body.arxivId().isBlank()) ? "arxiv" : "web";
        String originUrl = "arxiv".equals(origin)
                ? "https://export.arxiv.org/api/query?id_list=" + body.arxivId().trim()
                : body.url();

        jdbc.sql("""
                INSERT INTO core.source_documents (
                    id, source_id, status, origin, origin_url, mime, byte_size, rights_confirmed
                ) VALUES (
                    :did, :sid, 'queued', :origin, :url, 'text/html', 0, TRUE
                )
                """)
                .param("did", docId)
                .param("sid", sid)
                .param("origin", origin)
                .param("url", originUrl)
                .update();

        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("sourceId", IdCodec.format("src", sid));
        msg.put("documentId", IdCodec.format("doc", docId));
        msg.put("idempotencyKey", "ing_" + docId);
        msg.put("ownerId", IdCodec.format("usr", principal.userId()));
        msg.put("sourceKind", "arxiv".equals(origin) ? "arxiv_url" : "web_url");
        msg.put("url", originUrl);
        msg.put("ocrEnabled", false);
        msg.put("correlationId", "cor_" + docId.toString().replace("-", "").substring(0, 16));
        aiEngine.enqueueIngestJob(msg);

        return ResponseEntity.status(HttpStatus.ACCEPTED).body(getSourceDocument(principal, sourceId, IdCodec.format("doc", docId)));
    }

    @DeleteMapping("/v1/sources/{sourceId}/documents/{documentId}")
    @Transactional
    public ResponseEntity<Void> deleteSourceDocument(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String sourceId,
            @PathVariable String documentId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID sid = IdCodec.parse(sourceId, "src");
        UUID did = IdCodec.parse(documentId, "doc");
        loadOwnedSource(principal.userId(), sid);
        jdbc.sql("DELETE FROM core.source_documents WHERE id = :did AND source_id = :sid")
                .param("did", did).param("sid", sid).update();
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/v1/courses/{courseId}/sources")
    public Map<String, Object> listCourseSources(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        List<Map<String, Object>> links = jdbc.sql("""
                SELECT cs.course_id, cs.role, cs.evaluation_json, cs.linked_at,
                       s.id, s.source_type, s.title, s.canonical_url, s.author, s.publisher,
                       s.publication_date, s.source_updated_at, s.retrieved_at, s.language,
                       s.version, s.visibility, s.license_info, s.content_hash,
                       s.verification_status, s.owner_id, s.created_at,
                       s.brief, s.word_count, s.duration_minutes, s.suggested_topic, s.reject_reason,
                       s.external_key, s.domain_slug, s.pedagogy_tier, s.commercial_safe, s.isbn, s.doi
                FROM core.course_sources cs
                JOIN core.sources s ON s.id = cs.source_id
                WHERE cs.course_id = :cid
                ORDER BY CASE WHEN cs.role = 'primary' THEN 0 ELSE 1 END ASC, cs.linked_at DESC
                """)
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("courseId", IdCodec.format("crs", rs.getObject("course_id", UUID.class)));
                    item.put("role", rs.getString("role"));
                    item.put("source", mapSourceRow(rs, rowNum));
                    String ev = rs.getString("evaluation_json");
                    item.put("evaluation", ev == null ? null : json.fromJson(ev, new TypeReference<Map<String, Object>>() {}));
                    var la = rs.getTimestamp("linked_at");
                    item.put("linkedAt", la == null ? null : la.toInstant().toString());
                    return item;
                })
                .list();

        return Map.of(
                "items", links,
                "total", links.size(),
                "groundingAvailable", props.ragEnabled() && !links.isEmpty(),
                "contentIngested", !links.isEmpty(),
                "notice", links.isEmpty() ? "Khóa học chưa liên kết tài liệu nguồn." : ""
        );
    }

    @PostMapping("/v1/courses/{courseId}/sources")
    @Transactional
    public ResponseEntity<Map<String, Object>> linkCourseSource(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody LinkSourceRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID sid = IdCodec.parse(body.sourceId(), "src");
        verifyOwnedCourse(principal.userId(), cid);
        loadOwnedOrPublicSource(principal.userId(), sid);

        Integer existingLink = jdbc.sql("SELECT COUNT(*) FROM core.course_sources WHERE course_id = :cid AND source_id = :sid")
                .param("cid", cid).param("sid", sid).query(Integer.class).single();
        if (existingLink == null || existingLink == 0) {
            Integer currentCount = jdbc.sql("SELECT COUNT(*) FROM core.course_sources WHERE course_id = :cid")
                    .param("cid", cid).query(Integer.class).single();
            if (currentCount != null && currentCount >= 3) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "COURSE_SOURCE_LIMIT_REACHED", "Mỗi khóa học liên kết tối đa 3 tài liệu nguồn để tránh loãng kiến thức.");
            }
            Integer primaryCount = jdbc.sql("SELECT COUNT(*) FROM core.course_sources WHERE course_id = :cid AND role = 'primary'")
                    .param("cid", cid).query(Integer.class).single();
            String assignedRole = (primaryCount == null || primaryCount == 0) ? "primary" : "reference";

            jdbc.sql("""
                    INSERT INTO core.course_sources (id, course_id, source_id, role)
                    VALUES (:id, :cid, :sid, :role)
                    ON CONFLICT (course_id, source_id) DO NOTHING
                    """)
                    .param("id", UUID.randomUUID())
                    .param("cid", cid)
                    .param("sid", sid)
                    .param("role", assignedRole)
                    .update();
        }

        return ResponseEntity.status(HttpStatus.CREATED).body(listCourseSources(principal, courseId));
    }

    @PostMapping("/v1/courses/{courseId}/sources/search")
    @SuppressWarnings("unchecked")
    public Map<String, Object> searchCourseSources(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody SearchSourcesRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        // Server-authoritative sourceIds filtering: ONLY allow sources owned by current user OR visibility='public'
        List<String> authorizedSourceIds = new java.util.ArrayList<>();
        if (body.sourceIds() != null && !body.sourceIds().isEmpty()) {
            for (String rawSid : body.sourceIds()) {
                UUID parsedSid = IdCodec.parse(rawSid, "src");
                Integer allowed = jdbc.sql("""
                        SELECT COUNT(*) FROM core.sources
                        WHERE id = :sid AND (owner_id = :uid OR visibility = 'public')
                        """)
                        .param("sid", parsedSid)
                        .param("uid", principal.userId())
                        .query(Integer.class)
                        .single();
                if (allowed != null && allowed > 0) {
                    authorizedSourceIds.add(IdCodec.format("src", parsedSid));
                }
            }
            if (authorizedSourceIds.isEmpty()) {
                return Map.of(
                        "query", body.query(),
                        "embeddingSpec", "hashing/hashing-ngram-v1/d256/v1",
                        "items", List.of(),
                        "total", 0,
                        "insufficientEvidence", true,
                        "notice", "Không tìm thấy đoạn tài liệu phù hợp."
                );
            }
        } else {
            authorizedSourceIds = jdbc.sql("""
                    SELECT cs.source_id
                    FROM core.course_sources cs
                    JOIN core.sources s ON s.id = cs.source_id
                    WHERE cs.course_id = :cid AND (s.owner_id = :uid OR s.visibility = 'public')
                    ORDER BY CASE WHEN cs.role = 'primary' THEN 0 ELSE 1 END ASC
                    LIMIT 3
                    """)
                    .param("cid", cid)
                    .param("uid", principal.userId())
                    .query(UUID.class)
                    .list()
                    .stream()
                    .map(id -> IdCodec.format("src", id))
                    .toList();
        }

        Map<String, Object> aiReq = new LinkedHashMap<>();
        aiReq.put("ownerId", IdCodec.format("usr", principal.userId()));
        aiReq.put("courseId", IdCodec.format("crs", cid));
        aiReq.put("query", body.query());
        if (!authorizedSourceIds.isEmpty()) {
            aiReq.put("sourceIds", authorizedSourceIds);
        }
        aiReq.put("topK", 5);

        Map<String, Object> aiResp = aiEngine.postJson("/internal/rag/search", aiReq, null);
        List<Map<String, Object>> chunks = (List<Map<String, Object>>) aiResp.getOrDefault("chunks", List.of());

        List<Map<String, Object>> items = chunks.stream().map(c -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("chunkId", c.get("chunkId"));
            m.put("sourceId", c.get("sourceId"));
            m.put("documentId", c.getOrDefault("documentId", ""));
            m.put("pageNumber", c.getOrDefault("pageNumber", 1));
            m.put("charStart", 0);
            m.put("charEnd", 0);
            m.put("sectionAnchor", c.get("sectionAnchor"));
            m.put("textHash", "");
            m.put("sourceTitle", c.getOrDefault("sourceTitle", "Tài liệu"));
            m.put("sourceVersion", null);
            m.put("snippet", c.getOrDefault("content", ""));
            m.put("lexicalRank", null);
            m.put("vectorRank", null);
            m.put("similarity", null);
            m.put("rrfScore", c.getOrDefault("score", 0.0));
            return m;
        }).toList();

        return Map.of(
                "query", body.query(),
                "embeddingSpec", "hashing/hashing-ngram-v1/d256/v1",
                "items", items,
                "total", items.size(),
                "insufficientEvidence", items.isEmpty(),
                "notice", items.isEmpty() ? "Không tìm thấy đoạn tài liệu phù hợp." : ""
        );
    }

    // ---------- P2.SR Research Runs Parity ----------

    @PostMapping("/v1/courses/{courseId}/research-runs")
    @Transactional
    public ResponseEntity<Map<String, Object>> createResearchRun(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @RequestBody(required = false) ResearchRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "source_research", 10, 60);
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        String topic = jdbc.sql("SELECT topic FROM core.courses WHERE id = :cid")
                .param("cid", cid).query(String.class).single();
        int maxSources = (body != null && body.maxSources() != null)
                ? Math.max(1, Math.min(body.maxSources(), 3))
                : 3;
        String level = (body != null && body.learnerLevel() != null && !body.learnerLevel().isBlank())
                ? body.learnerLevel().trim().toLowerCase()
                : "beginner";
        String goals = (body != null && body.learningGoals() != null) ? body.learningGoals().trim() : "";
        String depth = (goals.toLowerCase().contains("deep") || goals.toLowerCase().contains("chuyên sâu") || "advanced".equals(level))
                ? "deep"
                : "practical";

        String effectiveQuery = (topic + " " + goals).trim();
        List<Map<String, Object>> candidates = rankPublicLibrarySources(effectiveQuery, null, level, depth, maxSources);

        UUID runId = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.source_research_runs (id, course_id, user_id, status, query_json, candidates_json)
                VALUES (:id, :cid, :uid, 'completed', CAST(:q AS jsonb), CAST(:cands AS jsonb))
                """)
                .param("id", runId)
                .param("cid", cid)
                .param("uid", principal.userId())
                .param("q", json.toJson(body == null ? Map.of("topic", topic) : body))
                .param("cands", json.toJson(candidates))
                .update();

        return ResponseEntity.status(HttpStatus.CREATED).body(Map.of(
                "id", IdCodec.format("run", runId),
                "courseId", IdCodec.format("crs", cid),
                "status", "completed",
                "reused", false,
                "candidates", candidates
        ));
    }

    @GetMapping("/v1/courses/{courseId}/research-runs")
    public Map<String, Object> listResearchRuns(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);
        List<Map<String, Object>> runs = jdbc.sql("""
                SELECT id, status, accepted, created_at
                FROM core.source_research_runs
                WHERE course_id = :cid AND user_id = :uid
                ORDER BY created_at DESC
                """)
                .param("cid", cid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", IdCodec.format("run", rs.getObject("id", UUID.class)),
                        "courseId", IdCodec.format("crs", cid),
                        "status", rs.getString("status"),
                        "accepted", rs.getBoolean("accepted"),
                        "candidates", List.of()
                ))
                .list();
        return Map.of("items", runs, "total", runs.size());
    }

    @GetMapping("/v1/courses/{courseId}/research-runs/{runId}")
    public Map<String, Object> getResearchRun(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String runId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID rid = IdCodec.parse(runId, "run");
        verifyOwnedCourse(principal.userId(), cid);
        return jdbc.sql("""
                SELECT id, status, accepted, candidates_json::text AS cands
                FROM core.source_research_runs
                WHERE id = :rid AND course_id = :cid AND user_id = :uid
                """)
                .param("rid", rid).param("cid", cid).param("uid", principal.userId())
                .query((rs, rowNum) -> {
                    String candsStr = rs.getString("cands");
                    List<Map<String, Object>> cands = (candsStr == null || candsStr.isBlank())
                            ? List.of()
                            : json.fromJson(candsStr, new TypeReference<List<Map<String, Object>>>() {});
                    return Map.<String, Object>of(
                            "id", IdCodec.format("run", rs.getObject("id", UUID.class)),
                            "courseId", IdCodec.format("crs", cid),
                            "status", rs.getString("status"),
                            "accepted", rs.getBoolean("accepted"),
                            "candidates", cands
                    );
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RESEARCH_RUN_NOT_FOUND", "Không tìm thấy phiên nghiên cứu."));
    }

    @PostMapping("/v1/courses/{courseId}/research-runs/{runId}/accept")
    @Transactional
    @SuppressWarnings("unchecked")
    public Map<String, Object> acceptResearchRun(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String runId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID rid = IdCodec.parse(runId, "run");
        verifyOwnedCourse(principal.userId(), cid);
        int updated = jdbc.sql("""
                UPDATE core.source_research_runs SET accepted = TRUE
                WHERE id = :rid AND course_id = :cid AND user_id = :uid
                """)
                .param("rid", rid).param("cid", cid).param("uid", principal.userId()).update();
        if (updated == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "RESEARCH_RUN_NOT_FOUND", "Không tìm thấy phiên nghiên cứu.");
        }
        Map<String, Object> run = getResearchRun(principal, courseId, runId);
        List<Map<String, Object>> candidates = (List<Map<String, Object>>) run.getOrDefault("candidates", List.of());
        int linkedCount = jdbc.sql("SELECT COUNT(*) FROM core.course_sources WHERE course_id = :cid")
                .param("cid", cid).query(Integer.class).single();
        int primaryCount = jdbc.sql("SELECT COUNT(*) FROM core.course_sources WHERE course_id = :cid AND role = 'primary'")
                .param("cid", cid).query(Integer.class).single();

        for (Map<String, Object> cand : candidates) {
            if (linkedCount >= 3) break;
            Object sidObj = cand.get("id");
            if (sidObj == null) continue;
            UUID sid;
            try {
                sid = IdCodec.parse(String.valueOf(sidObj), "src");
            } catch (Exception ex) {
                continue;
            }
            String role = (primaryCount == 0 && "primary".equals(cand.get("recommendedRole"))) ? "primary"
                    : (primaryCount == 0 ? "primary" : "reference");
            int ins = jdbc.sql("""
                    INSERT INTO core.course_sources (id, course_id, source_id, role)
                    VALUES (:id, :cid, :sid, :role)
                    ON CONFLICT (course_id, source_id) DO NOTHING
                    """)
                    .param("id", UUID.randomUUID())
                    .param("cid", cid)
                    .param("sid", sid)
                    .param("role", role)
                    .update();
            if (ins > 0) {
                linkedCount++;
                if ("primary".equals(role)) primaryCount++;
            }
        }
        return run;
    }

    private static final List<String[]> VI_TO_EN_DISCOVER_TERMS = List.of(
            new String[]{"lập trình", "programming"},
            new String[]{"khoa học máy tính", "computer science"},
            new String[]{"cấu trúc dữ liệu", "data structures"},
            new String[]{"thuật toán", "algorithms"},
            new String[]{"giải thuật", "algorithms"},
            new String[]{"cơ sở dữ liệu", "databases sql"},
            new String[]{"học máy", "machine learning"},
            new String[]{"học sâu", "deep learning neural"},
            new String[]{"trí tuệ nhân tạo", "artificial intelligence"},
            new String[]{"mô hình ngôn ngữ", "language model llm transformer"},
            new String[]{"hệ phân tán", "distributed consensus"},
            new String[]{"giao diện", "react nextjs frontend"},
            new String[]{"web", "mdn web http"},
            new String[]{"container", "kubernetes docker"},
            new String[]{"đám mây", "kubernetes cloud"},
            new String[]{"tối ưu hóa", "convex optimization"},
            new String[]{"giải tích", "calculus"},
            new String[]{"đại số tuyến tính", "linear algebra"},
            new String[]{"xác suất", "probability"},
            new String[]{"thống kê", "statistics"},
            new String[]{"toán rời rạc", "discrete mathematics"},
            new String[]{"vật lý", "physics"},
            new String[]{"hóa học", "chemistry"},
            new String[]{"sinh học", "biology"},
            new String[]{"giải phẫu", "anatomy physiology"},
            new String[]{"môi trường", "environmental climate"},
            new String[]{"thiết kế", "design architecture"},
            new String[]{"kiến trúc", "architecture design"},
            new String[]{"giao tiếp", "communication writing"},
            new String[]{"ngoại ngữ", "language english"},
            new String[]{"kinh tế vi mô", "microeconomics"},
            new String[]{"kinh tế vĩ mô", "macroeconomics"},
            new String[]{"kinh tế", "economics"},
            new String[]{"tài chính", "finance"},
            new String[]{"tâm lý", "psychology"},
            new String[]{"xã hội học", "sociology"},
            new String[]{"triết học", "philosophy"},
            new String[]{"lịch sử", "history"}
    );

    private static java.util.Set<String> tokenizeDiscoveryText(String text) {
        if (text == null || text.isBlank()) return java.util.Set.of();
        java.util.Set<String> set = new java.util.HashSet<>();
        for (String t : text.toLowerCase().split("[^\\p{L}\\p{Nd}+#]+")) {
            if (t.length() >= 2) {
                set.add(t);
            }
        }
        return set;
    }

    private List<Map<String, Object>> rankPublicLibrarySources(
            String rawQuery,
            String domainFilter,
            String learnerLevel,
            String depth,
            int limit
    ) {
        String qLower = rawQuery == null ? "" : rawQuery.trim().toLowerCase();
        List<String> rawTokens = java.util.Arrays.stream(qLower.split("[^\\p{L}\\p{Nd}+#]+"))
                .map(String::trim)
                .filter(t -> t.length() >= 2)
                .distinct()
                .toList();
        java.util.Set<String> rawTokenSet = new java.util.HashSet<>(rawTokens);
        java.util.Set<String> synonymTokens = new java.util.LinkedHashSet<>();
        for (String[] pair : VI_TO_EN_DISCOVER_TERMS) {
            if (qLower.contains(pair[0])) {
                for (String st : pair[1].split("\\s+")) {
                    if (st.length() >= 2 && !rawTokenSet.contains(st)) {
                        synonymTokens.add(st);
                    }
                }
            }
        }

        boolean strictCommercial = props.billingCommercialStrictSources();
        boolean deepMode = "advanced".equalsIgnoreCase(learnerLevel) || "deep".equalsIgnoreCase(depth);

        StringBuilder sql = new StringBuilder("""
                SELECT id, source_type, title, canonical_url, author, publisher, publication_date,
                       source_updated_at, retrieved_at, language, version, visibility, license_info,
                       content_hash, verification_status, owner_id, created_at,
                       brief, word_count, duration_minutes, suggested_topic, reject_reason,
                       external_key, domain_slug, pedagogy_tier, commercial_safe, isbn, doi
                FROM core.sources
                WHERE visibility = 'public'
                """);
        if (strictCommercial) {
            sql.append(" AND commercial_safe = TRUE ");
        }
        if (domainFilter != null && !domainFilter.isBlank()) {
            sql.append(" AND domain_slug = :domain ");
        }
        sql.append("""
                 ORDER BY CASE
                     WHEN pedagogy_tier = 'tier1_textbook' THEN 0
                     WHEN pedagogy_tier = 'official_docs' THEN 1
                     WHEN pedagogy_tier = 'tier2_monograph' THEN 2
                     ELSE 3
                 END ASC, created_at DESC LIMIT 2000
                """);

        var stmt = jdbc.sql(sql.toString());
        if (domainFilter != null && !domainFilter.isBlank()) {
            stmt = stmt.param("domain", domainFilter.trim().toLowerCase());
        }
        List<Map<String, Object>> allPublic = stmt.query(this::mapSourceRow).list();

        record Scored(Map<String, Object> row, int score, String tier) {}
        List<Scored> scored = new java.util.ArrayList<>();

        for (Map<String, Object> row : allPublic) {
            String tier = String.valueOf(row.getOrDefault("pedagogyTier", "tier2_monograph"));
            // Phase L4 Pedagogical Guard: exclude narrow `tier3_paper` (arXiv) for beginner/intermediate learners
            if (!deepMode && "tier3_paper".equals(tier)) {
                continue;
            }
            String title = String.valueOf(row.getOrDefault("title", "")).toLowerCase();
            String domainSlug = String.valueOf(row.getOrDefault("domainSlug", "")).toLowerCase();
            String suggested = String.valueOf(row.getOrDefault("suggestedTopic", "")).toLowerCase();
            String briefTxt = row.get("brief") == null ? "" : String.valueOf(row.get("brief")).toLowerCase();

            var titleWords = tokenizeDiscoveryText(title);
            var metaWords = tokenizeDiscoveryText(domainSlug + " " + suggested);
            var briefWords = tokenizeDiscoveryText(briefTxt);

            int relevance = 0;
            if (rawTokens.isEmpty() && synonymTokens.isEmpty()) {
                relevance = 10;
            } else {
                for (String tok : rawTokens) {
                    if (titleWords.contains(tok) || (tok.length() >= 4 && title.contains(tok))) relevance += 35;
                    else if (metaWords.contains(tok)) relevance += 16;
                    else if (briefWords.contains(tok)) relevance += 6;
                }
                for (String tok : synonymTokens) {
                    if (titleWords.contains(tok)) relevance += 14;
                    else if (metaWords.contains(tok)) relevance += 10;
                    else if (briefWords.contains(tok)) relevance += 3;
                }
            }
            if ((!rawTokens.isEmpty() || !synonymTokens.isEmpty()) && relevance == 0) {
                continue;
            }
            int tierBonus = switch (tier) {
                case "tier1_textbook" -> deepMode ? 22 : 45;
                case "official_docs" -> 30;
                case "tier2_monograph" -> deepMode ? 20 : 15;
                case "tier3_paper" -> deepMode ? 12 : -100;
                default -> 5;
            };
            scored.add(new Scored(row, relevance + tierBonus, tier));
        }

        scored.sort((a, b) -> Integer.compare(b.score(), a.score()));

        List<Map<String, Object>> selected = new java.util.ArrayList<>();
        if (deepMode) {
            // 1 tier1_textbook primary backbone + up to (limit - 1) deep monograph/paper references
            scored.stream()
                    .filter(s -> "tier1_textbook".equals(s.tier()))
                    .findFirst()
                    .ifPresent(primary -> {
                        Map<String, Object> copy = new LinkedHashMap<>(primary.row());
                        copy.put("recommendedRole", "primary");
                        copy.put("rankScore", primary.score());
                        selected.add(copy);
                    });
            for (Scored s : scored) {
                if (selected.size() >= limit) break;
                boolean already = selected.stream().anyMatch(x -> x.get("id").equals(s.row().get("id")));
                if (already) continue;
                Map<String, Object> copy = new LinkedHashMap<>(s.row());
                copy.put("recommendedRole", selected.isEmpty() ? "primary" : "reference");
                copy.put("rankScore", s.score());
                selected.add(copy);
            }
        } else {
            for (Scored s : scored) {
                if (selected.size() >= limit) break;
                Map<String, Object> copy = new LinkedHashMap<>(s.row());
                copy.put("recommendedRole", selected.isEmpty() ? "primary" : "reference");
                copy.put("rankScore", s.score());
                selected.add(copy);
            }
        }
        return selected;
    }

    private void verifyOwnedCourse(UUID userId, UUID courseId) {
        Integer cnt = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE id = :cid AND user_id = :uid")
                .param("cid", courseId).param("uid", userId).query(Integer.class).single();
        if (cnt == null || cnt == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học.");
        }
    }

    private void loadOwnedSource(UUID userId, UUID sourceId) {
        Integer cnt = jdbc.sql("SELECT COUNT(*) FROM core.sources WHERE id = :sid AND owner_id = :uid")
                .param("sid", sourceId).param("uid", userId).query(Integer.class).single();
        if (cnt == null || cnt == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "SOURCE_NOT_FOUND", "Không tìm thấy tài liệu nguồn.");
        }
    }

    private Map<String, Object> loadOwnedOrPublicSource(UUID userId, UUID sourceId) {
        return jdbc.sql("""
                SELECT id, source_type, title, canonical_url, author, publisher, publication_date,
                       source_updated_at, retrieved_at, language, version, visibility, license_info,
                       content_hash, verification_status, owner_id, created_at,
                       brief, word_count, duration_minutes, suggested_topic, reject_reason,
                       external_key, domain_slug, pedagogy_tier, commercial_safe, isbn, doi
                FROM core.sources
                WHERE id = :sid AND (owner_id = :uid OR visibility = 'public')
                """)
                .param("sid", sourceId)
                .param("uid", userId)
                .query(this::mapSourceRow)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "SOURCE_NOT_FOUND", "Không tìm thấy tài liệu nguồn."));
    }

    private Map<String, Object> mapSourceRow(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", IdCodec.format("src", rs.getObject("id", UUID.class)));
        m.put("sourceType", rs.getString("source_type"));
        m.put("title", rs.getString("title"));
        m.put("canonicalUrl", rs.getString("canonical_url"));
        m.put("author", rs.getString("author"));
        m.put("publisher", rs.getString("publisher"));
        m.put("publicationDate", rs.getString("publication_date"));
        m.put("sourceUpdatedAt", rs.getString("source_updated_at"));
        var ra = rs.getTimestamp("retrieved_at");
        m.put("retrievedAt", ra == null ? null : ra.toInstant().toString());
        m.put("language", rs.getString("language"));
        m.put("version", rs.getString("version"));
        m.put("visibility", rs.getString("visibility"));
        m.put("licenseInfo", rs.getString("license_info"));
        m.put("contentHash", rs.getString("content_hash"));
        m.put("verificationStatus", rs.getString("verification_status"));
        UUID ownerUuid = rs.getObject("owner_id", UUID.class);
        m.put("ownerId", ownerUuid == null ? "system:public_library" : IdCodec.format("usr", ownerUuid));
        var ca = rs.getTimestamp("created_at");
        m.put("createdAt", ca == null ? null : ca.toInstant().toString());
        String briefStr = rs.getString("brief");
        m.put("brief", briefStr == null ? null : json.fromJson(briefStr, new TypeReference<Map<String, Object>>() {}));
        m.put("wordCount", rs.getObject("word_count"));
        m.put("durationMinutes", rs.getObject("duration_minutes"));
        m.put("suggestedTopic", rs.getString("suggested_topic"));
        m.put("rejectReason", rs.getString("reject_reason"));
        m.put("externalKey", rs.getString("external_key"));
        m.put("domainSlug", rs.getString("domain_slug"));
        m.put("pedagogyTier", rs.getString("pedagogy_tier"));
        m.put("commercialSafe", rs.getBoolean("commercial_safe"));
        m.put("isbn", rs.getString("isbn"));
        m.put("doi", rs.getString("doi"));
        return m;
    }

    private Map<String, Object> mapDocumentRow(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", IdCodec.format("doc", rs.getObject("id", UUID.class)));
        m.put("sourceId", IdCodec.format("src", rs.getObject("source_id", UUID.class)));
        m.put("status", rs.getString("status"));
        m.put("origin", rs.getString("origin"));
        m.put("originUrl", rs.getString("origin_url"));
        m.put("mime", rs.getString("mime"));
        m.put("byteSize", rs.getLong("byte_size"));
        m.put("pageCount", rs.getObject("page_count"));
        m.put("pipelineVersion", rs.getString("pipeline_version"));
        m.put("originalFilename", rs.getString("original_filename"));
        m.put("chunkCount", rs.getInt("chunk_count"));
        m.put("preview", rs.getString("preview"));
        String errJson = rs.getString("error_json");
        m.put("error", errJson == null ? null : json.fromJson(errJson, new TypeReference<Map<String, Object>>() {}));
        m.put("attempts", rs.getInt("attempts"));
        m.put("rightsConfirmed", rs.getBoolean("rights_confirmed"));
        m.put("textSource", rs.getString("text_source"));
        m.put("ocrPages", rs.getInt("ocr_pages"));
        m.put("ocrEngine", rs.getString("ocr_engine"));
        m.put("ocrVersion", rs.getString("ocr_version"));
        var ia = rs.getTimestamp("ingested_at");
        m.put("ingestedAt", ia == null ? null : ia.toInstant().toString());
        var ca = rs.getTimestamp("created_at");
        m.put("createdAt", ca == null ? null : ca.toInstant().toString());
        return m;
    }
}
