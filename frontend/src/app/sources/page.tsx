"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  ApiError,
  createPrivateSource,
  deleteSource,
  deleteSourceDocument,
  documentStatusLabel,
  fetchSourceDocuments,
  fetchSourceIngestConfig,
  fetchSources,
  ingestWebDocument,
  uploadSourceDocument,
  verificationLabel,
  type SourceDocument,
} from "@/lib/api";
import { useAuth, useRequireAuth, useSession, useSessionQueryKey } from "../providers";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function DocRow({
  document,
  onDelete,
  busy,
}: {
  document: SourceDocument;
  onDelete: () => void;
  busy: boolean;
}) {
  // Chỉ `ready` mới là trạng thái đã có nội dung dùng được; còn lại hiển thị mờ
  // để người dùng không nhầm "đang chờ"/"không có text" là đã xong.
  const tone = document.status === "ready" ? "success" : "muted";
  const originLabel =
    document.origin === "web" ? "Từ URL" : document.origin === "arxiv" ? "arXiv" : null;
  return (
    <li>
      <strong>{document.originalFilename ?? "tài liệu"}</strong>{" "}
      <Badge tone={tone}>{documentStatusLabel(document.status)}</Badge>
      {originLabel && <Badge tone="muted">{originLabel}</Badge>}
      {document.textSource === "ocr" && (
        <Badge tone="muted">OCR {document.ocrPages ?? 0} trang</Badge>
      )}
      {document.textSource === "mixed" && <Badge tone="muted">text gốc + OCR</Badge>}
      {document.originUrl && (
        <a
          className="link"
          href={document.originUrl}
          target="_blank"
          rel="noopener noreferrer nofollow"
        >
          nguồn gốc
        </a>
      )}
      <div className="muted">
        {formatBytes(document.byteSize)}
        {document.pageCount != null && ` · ${document.pageCount} trang`}
        {document.status === "ready" && ` · ${document.chunkCount} đoạn text`}
        {document.status === "ready" && document.textSource === "ocr" && " · do máy đọc"}
        {document.rightsConfirmed && " · đã xác nhận quyền sử dụng"}
        {document.status === "ready" && document.preview && (
          <>
            <br />
            <span className="evidence-quote">{document.preview}…</span>
          </>
        )}
      </div>
      {document.error?.message && (
        <div className="error-text">
          {document.error.message}
          {document.attempts > 1 && ` (đã thử ${document.attempts} lần)`}
        </div>
      )}
      <Button variant="text" size="sm" disabled={busy} onClick={onDelete}>
        Xóa tài liệu
      </Button>
    </li>
  );
}

export default function SourcesPage() {
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const { epoch } = useSession();
  const { data: sessionUser } = useAuth();
  const queryClient = useQueryClient();
  // Scope key dùng cho invalidate từ event handler (KHÔNG gọi hook trong callback).
  const sessionScope = ["session", epoch, sessionUser?.id ?? "anon", "sources"];
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("vi");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const listKey = useSessionQueryKey("sources", "list");
  const configKey = useSessionQueryKey("sources", "config");

  const config = useQuery({
    queryKey: configKey,
    queryFn: fetchSourceIngestConfig,
    enabled: !!isAuthenticated,
    retry: false,
  });

  const sources = useQuery({
    queryKey: listKey,
    queryFn: () => fetchSources(50, 0),
    enabled: !!isAuthenticated,
    retry: false,
  });

  function invalidateSourceData() {
    // Invalidate cả list lẫn documents của mọi source (prefix match).
    queryClient.invalidateQueries({ queryKey: sessionScope });
  }

  const createSource = useMutation({
    mutationFn: async () => {
      const trimmed = title.trim();
      if (!trimmed) throw new Error("Cần nhập tên tài liệu.");
      return createPrivateSource({ title: trimmed, language: language || undefined });
    },
    onSuccess: (source) => {
      setTitle("");
      setError("");
      setStatus(`Đã tạo nguồn «${source.title}». Hãy chọn file PDF trong thẻ nguồn bên dưới.`);
      queryClient.invalidateQueries({ queryKey: listKey });
    },
    onError: (err) => {
      setStatus("");
      setError(err instanceof ApiError ? err.message : "Không tạo được nguồn.");
    },
  });

  const upload = useMutation({
    mutationFn: async ({ sourceId, file }: { sourceId: string; file: File }) => {
      return uploadSourceDocument(sourceId, file);
    },
    onSuccess: (document) => {
      setStatus(
        document.status === "ready"
          ? document.textSource === "ocr"
            ? "Đã đọc PDF scan bằng OCR — hãy kiểm tra lại nội dung trước khi dùng."
            : document.textSource === "mixed"
              ? "Đã trích xuất text gốc và OCR các trang scan."
              : "Đã trích xuất xong nội dung PDF."
          : document.status === "no_text"
            ? document.error?.code === "OCR_NO_TEXT"
              ? "OCR chạy xong nhưng không đọc được chữ nào trên tài liệu."
              : "PDF không có lớp text (có thể là bản scan); OCR chưa được bật."
            : "Đang xử lý tài liệu…"
      );
      setError("");
      invalidateSourceData();
    },
    onError: (err) => {
      setStatus("");
      setError(
        err instanceof ApiError
          ? `${err.code}: ${err.message}`
          : "Không tải lên được tài liệu."
      );
    },
  });

  const removeDocument = useMutation({
    mutationFn: ({ sourceId, documentId }: { sourceId: string; documentId: string }) =>
      deleteSourceDocument(sourceId, documentId),
    onSuccess: () => {
      setStatus("Đã xóa tài liệu.");
      invalidateSourceData();
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Không xóa được tài liệu.");
    },
  });

  const removeSource = useMutation({
    mutationFn: (sourceId: string) => deleteSource(sourceId),
    onSuccess: () => {
      setStatus("Đã xóa nguồn và toàn bộ nội dung đã trích xuất.");
      queryClient.invalidateQueries({ queryKey: listKey });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Không xóa được nguồn.");
    },
  });

  if (authLoading) {
    return (
      <div className="container">
        <div style={{ display: "grid", gap: 16 }}>
          <Skeleton height={28} width="40%" />
          <Skeleton height={180} />
        </div>
      </div>
    );
  }
  if (!isAuthenticated)
    return <div className="container">Đang chuyển tới trang đăng nhập…</div>;

  const uploadReady = config.data?.ingestEnabled && config.data?.storageConfigured;

  return (
    <div className="container">
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 20,
        }}
      >
        <div>
          <span className="eyebrow">Nguồn học liệu</span>
          <h1 className="page-title" style={{ margin: "4px 0 0" }}>
            Tài liệu của tôi
          </h1>
        </div>
        <ButtonLink href="/" variant="ghost" size="sm">
          ← Trang chủ
        </ButtonLink>
      </header>

      <Card>
        <h2 className="section-title" style={{ marginTop: 0 }}>
          Tải lên PDF
        </h2>
        <p className="muted">
          Chỉ tải tài liệu bạn có quyền sử dụng. File được lưu private và chỉ dùng để trích
          xuất text phục vụ học tập.
        </p>
        {config.data && !config.data.ragEnabled && (
          <div className="notice-box">
            Tìm kiếm tài liệu (RAG) đang <strong>tắt</strong> hoặc embedding chưa được cấu
            hình hợp lệ trên server. Nội dung vẫn được trích xuất nhưng trợ giảng sẽ không
            dùng để trả lời kèm trích dẫn.
          </div>
        )}
        {config.data && config.data.ragEnabled && (
          <p className="muted">
            Tìm kiếm đang dùng <code>{config.data.embeddingProvider}</code> /{" "}
            <code>{config.data.embeddingModel}</code> (dimension{" "}
            {config.data.embeddingDimension}). Nếu đây là embedding hashing, đây là baseline
            từ khoá, <strong>không</strong> phải semantic embedding của model thật.
          </p>
        )}
        {config.data && (
          <p className="muted">
            Giới hạn: tối đa {formatBytes(config.data.maxPdfBytes)} và{" "}
            {config.data.maxPdfPages} trang mỗi file.
          </p>
        )}
        {config.data && !config.data.ocrConfigured && (
          <div className="notice-box">
            OCR cho PDF scan đang <strong>tắt</strong>. Tài liệu scan (ảnh, không có lớp
            text) sẽ ở trạng thái «không có lớp text» — hệ thống không tự đoán nội dung.
          </div>
        )}
        {config.data && config.data.ocrConfigured && (
          <p className="muted">
            OCR đang bật: engine <code>{config.data.ocrEngine}</code> /{" "}
            <code>{config.data.ocrVersion}</code>, tối đa {config.data.ocrMaxPages} trang
            OCR mỗi tài liệu, render {config.data.ocrDpi} DPI. Text do máy đọc được ghi
            nhãn <strong>OCR</strong> và có thể sai (đặc biệt dấu tiếng Việt) — xem lại
            trước khi dùng làm căn cứ.
          </p>
        )}
        {config.data && !uploadReady && (
          <div className="notice-box">
            Kho lưu trữ hoặc tính năng ingest chưa được cấu hình trên server. Bạn vẫn có
            thể tạo nguồn, nhưng chưa tải được file.
          </div>
        )}
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "flex-end",
            marginTop: 12,
          }}
        >
          <div style={{ flex: "1 1 260px", minWidth: 0 }}>
            <TextInput
              id="source-title"
              type="text"
              label="Tên tài liệu"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Ví dụ: Giáo trình Python"
              maxLength={300}
            />
          </div>
          <div style={{ flex: "0 0 120px" }}>
            <TextInput
              id="source-language"
              type="text"
              label="Ngôn ngữ"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="vi"
              maxLength={20}
            />
          </div>
          <Button
            variant="primary"
            size="md"
            disabled={createSource.isPending}
            onClick={() => createSource.mutate()}
            className="source-create-btn"
          >
            {createSource.isPending ? "Đang tạo…" : "Tạo nguồn"}
          </Button>
        </div>
        {error && (
          <div className="error-box" role="alert">
            {error}
          </div>
        )}
        {status && <div className="notice-box">{status}</div>}
      </Card>

      {config.data?.ragEnabled && <RagSearchCard sourceCount={sources.data?.total ?? 0} />}

      <Card>
        <h2 className="section-title" style={{ marginTop: 0 }}>
          Nguồn đã đăng ký ({sources.data?.total ?? 0})
        </h2>
        {sources.isLoading && (
          <div style={{ display: "grid", gap: 12 }}>
            <Skeleton height={64} />
            <Skeleton height={64} />
          </div>
        )}
        {sources.isError && (
          <div className="error-box" role="alert">
            Không tải được danh sách nguồn: {sources.error.message}
          </div>
        )}
        {sources.data && sources.data.items.length === 0 && (
          <p className="muted">Chưa có tài liệu nào. Tạo nguồn rồi tải PDF ở trên.</p>
        )}
        {sources.data?.items.map((source) => (
          <SourceCard
            key={source.id}
            sourceId={source.id}
            title={source.title}
            language={source.language}
            contentHash={source.contentHash}
            verificationStatus={source.verificationStatus}
            uploadReady={!!uploadReady}
            webEnabled={!!config.data?.webEnabled}
            arxivEnabled={!!config.data?.arxivEnabled}
            webRespectRobots={config.data?.webRespectRobots ?? true}
            webMaxFetchBytes={config.data?.webMaxFetchBytes ?? 0}
            maxBytes={config.data?.maxPdfBytes ?? 0}
            onUpload={(file) => upload.mutate({ sourceId: source.id, file })}
            uploadBusy={upload.isPending && upload.variables?.sourceId === source.id}
            onDeleteDocument={(documentId) =>
              removeDocument.mutate({ sourceId: source.id, documentId })
            }
            documentBusy={
              removeDocument.isPending &&
              removeDocument.variables?.sourceId === source.id
            }
            sessionScope={sessionScope}
            onDeleteSource={() => removeSource.mutate(source.id)}
            deleteBusy={removeSource.isPending && removeSource.variables === source.id}
          />
        ))}
      </Card>
    </div>
  );
}

/**
 * Tìm kiếm tài liệu (P4.1). Chỉ gọi API search của COURSE; trang này chưa gắn
 * course nên hiển thị rõ phạm vi: muốn thử retrieval, mở một khóa học có nguồn.
 */
function RagSearchCard({ sourceCount }: { sourceCount: number }) {
  return (
    <Card variant="tint">
      <h2 className="section-title" style={{ marginTop: 0 }}>
        Tìm kiếm tài liệu
      </h2>
      <p className="muted">
        Tìm kiếm chạy trong phạm vi một khóa học đã liên kết nguồn — không phải toàn bộ
        tài khoản. Mở khóa học và dùng trợ giảng ở bài học để nhận câu trả lời kèm trích
        dẫn đã xác minh vị trí.
      </p>
      <p className="muted">
        Bạn có {sourceCount} nguồn. Trích dẫn chỉ hiển thị khi đoạn nguồn thực sự được
        truy xuất và khớp với chunk đã lưu.
      </p>
    </Card>
  );
}

function SourceCard({
  sourceId,
  title,
  language,
  contentHash,
  verificationStatus,
  uploadReady,
  webEnabled,
  arxivEnabled,
  webRespectRobots,
  webMaxFetchBytes,
  maxBytes,
  onUpload,
  uploadBusy,
  onDeleteDocument,
  documentBusy,
  onDeleteSource,
  deleteBusy,
  sessionScope,
}: {
  sourceId: string;
  title: string;
  language: string | null;
  contentHash: string | null;
  verificationStatus: string;
  uploadReady: boolean;
  webEnabled: boolean;
  arxivEnabled: boolean;
  webRespectRobots: boolean;
  webMaxFetchBytes: number;
  maxBytes: number;
  onUpload: (file: File) => void;
  uploadBusy: boolean;
  onDeleteDocument: (documentId: string) => void;
  documentBusy: boolean;
  onDeleteSource: () => void;
  deleteBusy: boolean;
  sessionScope: unknown[];
}) {
  const docsKey = [...sessionScope, "documents", sourceId];
  const queryClient = useQueryClient();
  const [localError, setLocalError] = useState("");

  const documents = useQuery({
    queryKey: docsKey,
    queryFn: () => fetchSourceDocuments(sourceId),
    retry: false,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const pending = items.some(
        (item) => item.status === "queued" || item.status === "extracting"
      );
      return pending ? 2000 : false;
    },
  });

  function pickFile(event: React.ChangeEvent<HTMLInputElement>) {
    setLocalError("");
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setLocalError("Chỉ nhận file PDF.");
      return;
    }
    if (maxBytes && file.size > maxBytes) {
      setLocalError(`File vượt giới hạn ${formatBytes(maxBytes)}.`);
      return;
    }
    onUpload(file);
  }

  return (
    <div className="source-item">
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <strong>{title}</strong>
        <Badge tone={contentHash ? "accent" : "muted"}>
          {verificationLabel(verificationStatus)}
        </Badge>
        {language && <span className="caption">{language}</span>}
      </div>
      <p className="caption">
        {contentHash
          ? `Nội dung đã trích xuất (hash ${contentHash.slice(0, 12)}…)`
          : "Chưa có nội dung được trích xuất."}
      </p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0", alignItems: "center" }}>
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={pickFile}
          disabled={!uploadReady || uploadBusy}
          aria-label={`Chọn PDF cho ${title}`}
        />
        {uploadBusy && <span className="caption">Đang tải lên…</span>}
      </div>
      {localError && (
        <div className="error-box" role="alert">
          {localError}
        </div>
      )}

      {webEnabled && (
        <WebIngestForm
          sourceId={sourceId}
          sourceTitle={title}
          arxivEnabled={arxivEnabled}
          webRespectRobots={webRespectRobots}
          maxBytes={webMaxFetchBytes}
          onDone={() => queryClient.invalidateQueries({ queryKey: docsKey })}
        />
      )}

      {documents.isLoading && (
        <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
          <Skeleton height={20} width="60%" />
          <Skeleton height={20} width="45%" />
        </div>
      )}
      {documents.isError && (
        <div className="error-box" role="alert">
          Không tải được tài liệu: {documents.error.message}
        </div>
      )}
      {documents.data && documents.data.items.length === 0 && (
        <p className="caption">Chưa có file nào cho nguồn này.</p>
      )}
      {documents.data && documents.data.notice && (
        <p className="caption">{documents.data.notice}</p>
      )}
      {documents.data && documents.data.items.length > 0 && (
        <ul className="source-list">
          {documents.data.items.map((document) => (
            <DocRow
              key={document.id}
              document={document}
              busy={documentBusy}
              onDelete={() => onDeleteDocument(document.id)}
            />
          ))}
        </ul>
      )}

      <Button variant="text" size="sm" disabled={deleteBusy} onClick={onDeleteSource}>
        Xóa nguồn
      </Button>
    </div>
  );
}

/**
 * P4.2 — ingest từ URL/arXiv. Quyền sử dụng là checkbox BẮT BUỘC: server trả 422
 * nếu client không xác nhận, và lưu lại mốc thời gian xác nhận.
 */
function WebIngestForm({
  sourceId,
  sourceTitle,
  arxivEnabled,
  webRespectRobots,
  maxBytes,
  onDone,
}: {
  sourceId: string;
  sourceTitle: string;
  arxivEnabled: boolean;
  webRespectRobots: boolean;
  maxBytes: number;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<"url" | "arxiv">("url");
  const [value, setValue] = useState("");
  const [rights, setRights] = useState(false);
  const [localError, setLocalError] = useState("");
  const [localStatus, setLocalStatus] = useState("");

  const ingest = useMutation({
    mutationFn: async () => {
      const trimmed = value.trim();
      if (!trimmed) throw new Error(mode === "url" ? "Cần nhập URL." : "Cần nhập ID arXiv.");
      if (!rights) throw new Error("Bạn phải xác nhận có quyền sử dụng nội dung nguồn.");
      return ingestWebDocument(sourceId, {
        ...(mode === "url" ? { url: trimmed } : { arxivId: trimmed }),
        userConfirmedRights: rights,
      });
    },
    onSuccess: (document) => {
      setLocalError("");
      setValue("");
      setLocalStatus(
        document.status === "ready"
          ? "Đã trích xuất nội dung từ nguồn."
          : document.status === "no_text"
            ? "Nguồn không có văn bản trích xuất được."
            : "Đang xử lý nội dung nguồn…"
      );
      onDone();
    },
    onError: (err) => {
      setLocalStatus("");
      setLocalError(
        err instanceof ApiError ? `${err.code}: ${err.message}` : (err as Error).message
      );
    },
  });

  return (
    <div className="web-ingest">
      <p className="caption" style={{ marginBottom: 8 }}>
        Hoặc ingest từ nguồn web{arxivEnabled ? "/arXiv" : ""} — chỉ dùng nội dung bạn có
        quyền sử dụng.
        {webRespectRobots && " Server sẽ tôn trọng robots.txt của trang nguồn."}
        {maxBytes > 0 && ` Giới hạn ${formatBytes(maxBytes)} mỗi lần tải.`}
      </p>
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginBottom: 8,
          alignItems: "center",
        }}
      >
        <select
          value={mode}
          onChange={(event) => setMode(event.target.value as "url" | "arxiv")}
          aria-label={`Loại nguồn cho ${sourceTitle}`}
        >
          <option value="url">URL</option>
          {arxivEnabled && <option value="arxiv">arXiv ID</option>}
        </select>
        <input
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={mode === "url" ? "https://…" : "2401.12345"}
          aria-label={mode === "url" ? "URL nguồn" : "ID arXiv"}
          maxLength={2048}
          style={{ flex: "1 1 300px" }}
        />
        <Button
          variant="secondary"
          size="sm"
          disabled={ingest.isPending || !rights || !value.trim()}
          onClick={() => ingest.mutate()}
        >
          {ingest.isPending ? "Đang tải…" : "Ingest"}
        </Button>
      </div>
      <label className="caption" style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          type="checkbox"
          checked={rights}
          onChange={(event) => setRights(event.target.checked)}
        />
        Tôi xác nhận có quyền sử dụng và ingest nội dung này cho mục đích học tập.
      </label>
      {localError && (
        <div className="error-box" role="alert">
          {localError}
        </div>
      )}
      {localStatus && <div className="notice-box">{localStatus}</div>}
    </div>
  );
}
