"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
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
  const tone = document.status === "ready" ? "" : "badge-muted";
  const originLabel =
    document.origin === "web" ? "Từ URL" : document.origin === "arxiv" ? "arXiv" : null;
  return (
    <li>
      <strong>{document.originalFilename ?? "tài liệu"}</strong>{" "}
      <span className={`badge ${tone}`}>{documentStatusLabel(document.status)}</span>
      {originLabel && <span className="badge badge-muted"> {originLabel}</span>}{" "}
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
        {document.rightsConfirmed && " · đã xác nhận quyền sử dụng"}
        {document.status === "ready" && document.preview && (
          <>
            <br />
            <span className="evidence-quote">{document.preview}…</span>
          </>
        )}
      </div>
      {document.error?.message && (
        <div className="muted" style={{ color: "#b91c1c" }}>
          {document.error.message}
          {document.attempts > 1 && ` (đã thử ${document.attempts} lần)`}
        </div>
      )}
      <button
        type="button"
        className="link-btn"
        disabled={busy}
        onClick={onDelete}
      >
        Xóa tài liệu
      </button>
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
    onSuccess: (document, variables) => {
      setStatus(
        document.status === "ready"
          ? "Đã trích xuất xong nội dung PDF."
          : document.status === "no_text"
            ? "PDF không có lớp text (có thể là bản scan); OCR chưa được bật."
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
    onSuccess: (_result, variables) => {
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

  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated)
    return <div className="container">Đang chuyển tới trang đăng nhập…</div>;

  const uploadReady = config.data?.ingestEnabled && config.data?.storageConfigured;

  return (
    <div className="container">
      <div className="topbar">
        <h1>Tài liệu của tôi</h1>
        <Link href="/" className="link">
          ← Trang chủ
        </Link>
      </div>

      <div className="card">
        <h2>Tải lên PDF</h2>
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
        {config.data && !uploadReady && (
          <div className="notice-box">
            Kho lưu trữ hoặc tính năng ingest chưa được cấu hình trên server. Bạn vẫn có
            thể tạo nguồn, nhưng chưa tải được file.
          </div>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          <input
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Tên tài liệu (ví dụ: Giáo trình Python)"
            maxLength={300}
            style={{ flex: "1 1 260px" }}
          />
          <input
            type="text"
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            placeholder="Ngôn ngữ"
            maxLength={20}
            style={{ flex: "0 0 120px" }}
          />
          <button
            type="button"
            disabled={createSource.isPending}
            onClick={() => createSource.mutate()}
          >
            Tạo nguồn
          </button>
        </div>
        {error && <div className="error-box">{error}</div>}
        {status && <div className="notice-box">{status}</div>}
      </div>

      {config.data?.ragEnabled && <RagSearchCard sourceCount={sources.data?.total ?? 0} />}

      <div className="card">
        <h2>Nguồn đã đăng ký ({sources.data?.total ?? 0})</h2>
        {sources.isLoading && <p>Đang tải…</p>}
        {sources.isError && (
          <div className="error-box">
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
      </div>
    </div>
  );
}

/**
 * Tìm kiếm tài liệu (P4.1). Chỉ gọi API search của COURSE; trang này chưa gắn
 * course nên hiển thị rõ phạm vi: muốn thử retrieval, mở một khóa học có nguồn.
 */
function RagSearchCard({ sourceCount }: { sourceCount: number }) {
  return (
    <div className="card">
      <h2>Tìm kiếm tài liệu</h2>
      <p className="muted">
        Tìm kiếm chạy trong phạm vi một khóa học đã liên kết nguồn — không phải toàn bộ
        tài khoản. Mở khóa học và dùng trợ giảng ở bài học để nhận câu trả lời kèm trích
        dẫn đã xác minh vị trí.
      </p>
      <p className="muted">
        Bạn có {sourceCount} nguồn. Trích dẫn chỉ hiển thị khi đoạn nguồn thực sự được
        truy xuất và khớp với chunk đã lưu.
      </p>
    </div>
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
    <div className="source-card" style={{ borderTop: "1px solid #e3e6ee", paddingTop: 12 }}>
      <strong>{title}</strong>{" "}
      <span className={`badge ${contentHash ? "" : "badge-muted"}`}>
        {verificationLabel(verificationStatus)}
      </span>
      {language && <span className="muted"> · {language}</span>}
      <div className="muted">
        {contentHash
          ? `Nội dung đã trích xuất (hash ${contentHash.slice(0, 12)}…)`
          : "Chưa có nội dung được trích xuất."}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={pickFile}
          disabled={!uploadReady || uploadBusy}
          aria-label={`Chọn PDF cho ${title}`}
        />
        {uploadBusy && <span className="muted">Đang tải lên…</span>}
      </div>
      {localError && <div className="error-box">{localError}</div>}

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

      {documents.isLoading && <p className="muted">Đang tải tài liệu…</p>}
      {documents.isError && (
        <div className="error-box">Không tải được tài liệu: {documents.error.message}</div>
      )}
      {documents.data && documents.data.items.length === 0 && (
        <p className="muted">Chưa có file nào cho nguồn này.</p>
      )}
      {documents.data && documents.data.notice && (
        <p className="muted">{documents.data.notice}</p>
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

      <button
        type="button"
        className="link-btn"
        disabled={deleteBusy}
        onClick={onDeleteSource}
      >
        Xóa nguồn
      </button>
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
    <div style={{ margin: "12px 0", paddingTop: 8, borderTop: "1px dashed #e3e6ee" }}>
      <div className="muted" style={{ marginBottom: 6 }}>
        Hoặc ingest từ nguồn web{arxivEnabled ? "/arXiv" : ""} — chỉ dùng nội dung bạn có
        quyền sử dụng.
        {webRespectRobots && " Server sẽ tôn trọng robots.txt của trang nguồn."}
        {maxBytes > 0 && ` Giới hạn ${formatBytes(maxBytes)} mỗi lần tải.`}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
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
        <button
          type="button"
          disabled={ingest.isPending || !rights || !value.trim()}
          onClick={() => ingest.mutate()}
        >
          {ingest.isPending ? "Đang tải…" : "Ingest"}
        </button>
      </div>
      <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          type="checkbox"
          checked={rights}
          onChange={(event) => setRights(event.target.checked)}
        />
        Tôi xác nhận có quyền sử dụng và ingest nội dung này cho mục đích học tập.
      </label>
      {localError && <div className="error-box">{localError}</div>}
      {localStatus && <div className="notice-box">{localStatus}</div>}
    </div>
  );
}
