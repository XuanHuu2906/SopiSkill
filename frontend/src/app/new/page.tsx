"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, newClientId, type CourseLanguage } from "@/lib/api";
import { useRequireAuth } from "../providers";
import { Button } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Field";
import Icon from "@/components/ui/Icon";

interface CourseOut {
  id: string;
  topic: string;
  status: string;
  language?: CourseLanguage;
}

const SUGGESTIONS = [
  "Python cho người mới",
  "Xác suất thống kê cơ bản",
  "Cách hoạt động của LLM",
  "Nhạc lý cơ bản",
];

const LANGUAGES: { value: CourseLanguage; label: string }[] = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "English" },
];

const YOUTUBE_URL_RE = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)\b/i;

export default function NewCoursePage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<CourseLanguage>("vi");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(value?: string) {
    const finalTopic = (value ?? topic).trim();
    if (!finalTopic) return;
    if (YOUTUBE_URL_RE.test(finalTopic)) {
      setError("Hiện chưa hỗ trợ tạo khóa học trực tiếp từ liên kết YouTube. Hãy nhập chủ đề học tập hoặc tải lên tệp PDF.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const course = await api<CourseOut>("/v1/courses", {
        method: "POST",
        body: { topic: finalTopic, clientCourseId: newClientId("cc"), language },
      });
      router.push(`/new/interview?courseId=${encodeURIComponent(course.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setLoading(false);
    }
  }

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", paddingTop: 24 }}>
      <h1 className="display-xl" style={{ marginBottom: 12 }}>
        Bạn muốn học gì?
      </h1>
      <p className="lede" style={{ marginBottom: 28 }}>
        Nêu một chủ đề bất kỳ. Hệ thống sẽ hỏi vài câu nhanh rồi soạn khóa học phù hợp
        với bạn.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <TextInput
          id="topic-input"
          label="Chủ đề khóa học"
          type="text"
          placeholder="Ví dụ: Python cho người mới"
          value={topic}
          maxLength={200}
          onChange={(e) => setTopic(e.target.value)}
          autoFocus
        />
        <div className="field" role="group" aria-labelledby="course-language-label">
          <span id="course-language-label" className="field-label">
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
                  disabled={loading}
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
        {error && (
          <div className="error-box" role="alert">
            {error}
          </div>
        )}
        <Button type="submit" size="lg" block disabled={loading || !topic.trim()}>
          {loading ? "Đang tạo..." : "Bắt đầu"}
        </Button>
      </form>

      <div style={{ marginTop: 28 }}>
        <span className="eyebrow" style={{ color: "var(--ink-3)" }}>
          Cần gợi ý?
        </span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="quick-chip"
              disabled={loading}
              onClick={() => {
                setTopic(s);
                void start(s);
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <Link href="/new/source" className="home-review-banner" style={{ marginTop: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span className="profile-stat-icon" style={{ marginBottom: 0 }} aria-hidden="true">
            <Icon name="file" size={18} />
          </span>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>
              Tạo khóa học từ tài liệu của bạn
            </div>
            <div style={{ fontSize: 14, color: "var(--ink-2)", marginTop: 2 }}>
              Tải lên PDF hoặc gắn nguồn bài báo / web để bài giảng bám sát tài liệu gốc.
            </div>
          </div>
        </div>
        <Icon name="arrowRight" size={18} />
      </Link>
    </div>
  );
}
