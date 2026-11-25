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

    public SourcesAndResearchController(
            JdbcClient jdbc,
            JsonHelper json,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            SopiProperties props,
            AiEngineClient aiEngine
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.props = props;
        this.aiEngine = aiEngine;
    }

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
                       content_hash, verification_status, owner_id, created_at
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
    public Map<String, Object> discoverSources(@RequestParam(defaultValue = "") String q) {
        return Map.of("query", q, "items", List.of(), "total", 0);
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
                SELECT cs.course_id, cs.evaluation_json, cs.linked_at,
                       s.id, s.source_type, s.title, s.canonical_url, s.author, s.publisher,
                       s.publication_date, s.source_updated_at, s.retrieved_at, s.language,
                       s.version, s.visibility, s.license_info, s.content_hash,
                       s.verification_status, s.owner_id, s.created_at
                FROM core.course_sources cs
                JOIN core.sources s ON s.id = cs.source_id
                WHERE cs.course_id = :cid
                ORDER BY cs.linked_at DESC
                """)
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("courseId", IdCodec.format("crs", rs.getObject("course_id", UUID.class)));
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

        jdbc.sql("""
                INSERT INTO core.course_sources (id, course_id, source_id)
                VALUES (:id, :cid, :sid)
                ON CONFLICT (course_id, source_id) DO NOTHING
                """)
                .param("id", UUID.randomUUID())
                .param("cid", cid)
                .param("sid", sid)
                .update();

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

        Map<String, Object> aiReq = new LinkedHashMap<>();
        aiReq.put("ownerId", IdCodec.format("usr", principal.userId()));
        aiReq.put("courseId", IdCodec.format("crs", cid));
        aiReq.put("query", body.query());
        if (body.sourceIds() != null && !body.sourceIds().isEmpty()) {
            aiReq.put("sourceIds", body.sourceIds());
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

        UUID runId = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.source_research_runs (id, course_id, user_id, status, query_json, candidates_json)
                VALUES (:id, :cid, :uid, 'completed', CAST(:q AS jsonb), '[]'::jsonb)
                """)
                .param("id", runId)
                .param("cid", cid)
                .param("uid", principal.userId())
                .param("q", json.toJson(body == null ? Map.of() : body))
                .update();

        return ResponseEntity.status(HttpStatus.CREATED).body(Map.of(
                "id", IdCodec.format("run", runId),
                "courseId", IdCodec.format("crs", cid),
                "status", "completed",
                "reused", false,
                "candidates", List.of()
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
                SELECT id, status, accepted FROM core.source_research_runs
                WHERE id = :rid AND course_id = :cid AND user_id = :uid
                """)
                .param("rid", rid).param("cid", cid).param("uid", principal.userId())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", IdCodec.format("run", rs.getObject("id", UUID.class)),
                        "courseId", IdCodec.format("crs", cid),
                        "status", rs.getString("status"),
                        "accepted", rs.getBoolean("accepted"),
                        "candidates", List.of()
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RESEARCH_RUN_NOT_FOUND", "Không tìm thấy phiên nghiên cứu."));
    }

    @PostMapping("/v1/courses/{courseId}/research-runs/{runId}/accept")
    @Transactional
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
        return getResearchRun(principal, courseId, runId);
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
                       content_hash, verification_status, owner_id, created_at
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
        m.put("ownerId", IdCodec.format("usr", rs.getObject("owner_id", UUID.class)));
        var ca = rs.getTimestamp("created_at");
        m.put("createdAt", ca == null ? null : ca.toInstant().toString());
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
