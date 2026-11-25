"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  api,
  documentStatusLabel,
  fetchSource,
  fetchSourceDocuments,
  newClientId,
  presignSourceUpload,
  putPresignedFile,
  triggerSourceIngest,
  type CourseLanguage,
} from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";
import Icon from "@/components/ui/Icon";

const MAX_PDF_BYTES = 25 * 1024 * 1024;

const LANGUAGES: { value: CourseLanguage; label: string }[] = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "English" },
];

export default function NewCourseFromSourcePage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [titleInput, setTitleInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);

  const [courseTopic, setCourseTopic] = useState("");
  const [language, setLanguage] = useState<CourseLanguage>("vi");
  const [creatingCourse, setCreatingCourse] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const sourceKey = useSessionQueryKey("new-source", sourceId ?? "");
  const docsKey = useSessionQueryKey("new-source-docs", sourceId ?? "");

  const docsQuery = useQuery({
    queryKey: docsKey,
    enabled: !!sourceId && isAuthenticated,
    queryFn: () => fetchSourceDocuments(sourceId!),
    refetchInterval: (query) => {
      const latest = query.state.data?.items?.[0];
      if (!latest) return 1500;
      return ["ready", "no_text", "failed"].includes(latest.status) ? false : 1500;
    },
  });

  const latestDoc = docsQuery.data?.items?.[0] ?? null;
  const ingestDone = latestDoc ? ["ready", "no_text", "failed"].includes(latestDoc.status) : false;

  const sourceQuery = useQuery({
    queryKey: sourceKey,
    enabled: !!sourceId && isAuthenticated,
    queryFn: () => fetchSource(sourceId!),
    refetchInterval: () => {
      if (!sourceId || ingestDone) return false;
      return 1500;
    },
  });

  useEffect(() => {
    if (ingestDone && sourceId) {
      void sourceQuery.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ingestDone, sourceId]);

  useEffect(() => {
    const suggested = sourceQuery.data?.suggestedTopic || sourceQuery.data?.title || "";
    if (suggested && !courseTopic) {
      setCourseTopic(suggested);
    }
  }, [sourceQuery.data?.suggestedTopic, sourceQuery.data?.title, courseTopic]);

  async function handleFileUpload(file: File | null) {
    if (!file) return;
    setUploadError(null);
    if (file.type && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Chỉ hỗ trợ tệp PDF (application/pdf).");
      return;
    }
    if (file.size <= 0 || file.size > MAX_PDF_BYTES) {
      setUploadError("Dung lượng PDF phải lớn hơn 0 và không vượt quá 25 MB.");
      return;
    }

    setSelectedFile(file);
    setUploading(true);
    setSourceId(null);
    setCourseTopic("");
    try {
      const presigned = await presignSourceUpload({
        filename: file.name,
        contentType: "application/pdf",
        byteSize: file.size,
        title: titleInput.trim() || undefined,
      });
      await putPresignedFile(presigned.uploadUrl, file);
      await triggerSourceIngest(presigned.sourceId, { documentId: presigned.documentId });
      setSourceId(presigned.sourceId);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Tải tệp lên thất bại.");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateCourse() {
    if (!sourceId) return;
    const topic = (courseTopic || sourceQuery.data?.suggestedTopic || sourceQuery.data?.title || "").trim();
    if (!topic) return;
    setCreatingCourse(true);
    setCreateError(null);
    try {
      const course = await api<{ id: string }>("/v1/courses", {
        method: "POST",
        body: {
          topic,
          language,
          sourceId,
          clientCourseId: newClientId("cc"),
        },
      });
      router.push(`/new/interview?courseId=${encodeURIComponent(course.id)}`);
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Không tạo được khóa học.");
    } finally {
      setCreatingCourse(false);
    }
  }

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const brief = sourceQuery.data?.brief ?? null;
  const isReady = latestDoc?.status === "ready";
  const isFailed = latestDoc?.status === "failed" || latestDoc?.status === "no_text";

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", paddingTop: 16 }}>
      <div style={{ marginBottom: 18 }}>
        <Link href="/new" className="link" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Icon name="arrowLeft" size={16} />
          Quay lại nhập chủ đề
        </Link>
      </div>

      <h1 className="display-xl" style={{ marginBottom: 10 }}>
        Tạo khóa học từ tài liệu
      </h1>
      <p className="lede" style={{ marginBottom: 24 }}>
        Tải lên tệp PDF (tối đa 25 MB). Hệ thống sẽ trích xuất nội dung, tóm tắt cấu trúc tài liệu
        và biên soạn khóa học bám sát nguồn gốc.
      </p>

      <Card style={{ marginBottom: 20 }}>
        <TextInput
          id="source-title-input"
          label="Tên tài liệu (tùy chọn)"
          type="text"
          placeholder="Để trống để dùng tên tệp PDF"
          value={titleInput}
          maxLength={180}
          onChange={(e) => setTitleInput(e.target.value)}
          disabled={uploading}
        />

        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="pdf-upload-input" className="field-label">
            Chọn tệp PDF (tối đa 25 MB)
          </label>
          <input
            id="pdf-upload-input"
            type="file"
            accept="application/pdf,.pdf"
            disabled={uploading}
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null;
              void handleFileUpload(file);
            }}
            style={{
              display: "block",
              width: "100%",
              padding: "14px 12px",
              borderRadius: "var(--radius-md)",
              border: "1px dashed var(--line-strong)",
              background: "var(--surface-2)",
              color: "var(--ink)",
              cursor: uploading ? "wait" : "pointer",
            }}
          />
          {selectedFile && (
            <p className="field-hint" style={{ marginTop: 8 }}>
              Đã chọn: {selectedFile.name} ({Math.max(1, Math.round(selectedFile.size / 1024))} KB)
            </p>
          )}
        </div>

        {uploading && (
          <p className="muted" role="status" style={{ marginTop: 12 }}>
            Đang tải PDF trực tiếp lên kho lưu trữ và gửi yêu cầu phân tích…
          </p>
        )}

        {uploadError && (
          <div className="error-box" role="alert" style={{ marginTop: 12 }}>
            {uploadError}
          </div>
        )}
      </Card>

      {sourceId && (
        <Card style={{ marginBottom: 20 }} aria-live="polite">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div>
              <span className="eyebrow">Thẻ tài liệu nguồn</span>
              <h2 className="section-title" style={{ margin: "4px 0 0" }}>
                {sourceQuery.data?.title ?? selectedFile?.name ?? "Tài liệu PDF"}
              </h2>
            </div>
            <Badge tone={isReady ? "success" : isFailed ? "danger" : "muted"}>
              {latestDoc ? documentStatusLabel(latestDoc.status) : "Đang phân tích…"}
            </Badge>
          </div>

          <div className="caption" style={{ marginTop: 8, display: "flex", gap: 12, flexWrap: "wrap" }}>
            {sourceQuery.data?.wordCount != null && (
              <span>{sourceQuery.data.wordCount.toLocaleString("vi-VN")} từ</span>
            )}
            {sourceQuery.data?.durationMinutes != null && (
              <span>~{sourceQuery.data.durationMinutes} phút đọc</span>
            )}
            {latestDoc?.chunkCount != null && latestDoc.chunkCount > 0 && (
              <span>{latestDoc.chunkCount} đoạn đã lập chỉ mục</span>
            )}
          </div>

          {!ingestDone && (
            <p className="muted" style={{ marginTop: 14 }}>
              Đang trích xuất văn bản, tạo vector tìm kiếm và tổng hợp tóm tắt nguồn…
            </p>
          )}

          {isFailed && (
            <div className="error-box" role="alert" style={{ marginTop: 14 }}>
              {sourceQuery.data?.rejectReason ||
                latestDoc?.error?.message ||
                "Không thể trích xuất văn bản từ tệp PDF này."}
            </div>
          )}

          {isReady && brief && (
            <div style={{ marginTop: 18, display: "grid", gap: 14 }}>
              <div>
                <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px" }}>Tóm tắt nội dung</h3>
                <p style={{ margin: 0, color: "var(--ink-2)", lineHeight: 1.6 }}>{brief.what}</p>
              </div>

              {brief.claims.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px" }}>Luận điểm chính</h3>
                  <ul style={{ margin: 0, paddingLeft: 20, color: "var(--ink-2)", display: "grid", gap: 4 }}>
                    {brief.claims.slice(0, 6).map((c, idx) => (
                      <li key={idx}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}

              {brief.notation.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px" }}>Thuật ngữ & ký hiệu</h3>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {brief.notation.slice(0, 10).map((n, idx) => (
                      <Badge key={idx} tone="muted">
                        {n}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {brief.assumes.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px" }}>Kiến thức nền giả định</h3>
                  <ul style={{ margin: 0, paddingLeft: 20, color: "var(--ink-2)" }}>
                    {brief.assumes.slice(0, 5).map((a, idx) => (
                      <li key={idx}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              {brief.sections.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px" }}>
                    Cấu trúc tài liệu ({brief.sections.length} mục)
                  </h3>
                  <ol style={{ margin: 0, paddingLeft: 20, color: "var(--ink-2)", display: "grid", gap: 4 }}>
                    {brief.sections.slice(0, 8).map((sec, idx) => (
                      <li key={`${sec.anchor}-${idx}`}>
                        <strong style={{ color: "var(--ink)" }}>{sec.heading}</strong>
                        {sec.gist ? ` — ${sec.gist}` : ""}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}

          {isReady && (
            <div style={{ marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
              <TextInput
                id="source-course-topic"
                label="Tên chủ đề khóa học"
                type="text"
                value={courseTopic}
                maxLength={200}
                onChange={(e) => setCourseTopic(e.target.value)}
                placeholder="Nhập chủ đề khóa học từ tài liệu này"
              />

              <div className="field" role="group" aria-labelledby="source-language-label" style={{ marginTop: 12 }}>
                <span id="source-language-label" className="field-label">
                  Ngôn ngữ khóa học
                </span>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {LANGUAGES.map((opt) => {
                    const active = language === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        className="quick-chip"
                        aria-pressed={active}
                        disabled={creatingCourse}
                        style={
                          active
                            ? {
                                borderColor: "var(--ember)",
                                background: "var(--wash)",
                                color: "var(--ember-deep)",
                                fontWeight: 600,
                              }
                            : undefined
                        }
                        onClick={() => setLanguage(opt.value)}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {createError && (
                <div className="error-box" role="alert" style={{ marginTop: 12 }}>
                  {createError}
                </div>
              )}

              <Button
                size="lg"
                block
                style={{ marginTop: 14 }}
                disabled={creatingCourse || !courseTopic.trim()}
                onClick={() => void handleCreateCourse()}
              >
                {creatingCourse ? "Đang khởi tạo khóa học…" : "Tạo khóa học từ tài liệu này"}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
