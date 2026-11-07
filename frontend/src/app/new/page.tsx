"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, newClientId } from "@/lib/api";
import { useRequireAuth } from "../providers";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TextInput } from "@/components/ui/Field";

interface CourseOut {
  id: string;
  topic: string;
  status: string;
}

const SUGGESTIONS = [
  "Python cho người mới",
  "Xác suất thống kê cơ bản",
  "Cách hoạt động của LLM",
  "Nhạc lý cơ bản",
];

export default function NewCoursePage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const [topic, setTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(value?: string) {
    const finalTopic = (value ?? topic).trim();
    if (!finalTopic) return;
    setLoading(true);
    setError(null);
    try {
      const course = await api<CourseOut>("/v1/courses", {
        method: "POST",
        body: { topic: finalTopic, clientCourseId: newClientId("cc") },
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

      <Card variant="tint" className="card" style={{ marginTop: 28 }}>
        <h2 className="section-title" style={{ fontSize: 19, marginBottom: 6 }}>
          Bạn luôn có thể dừng giữa chừng
        </h2>
        <p className="muted">
          Câu trả lời phỏng vấn được lưu theo từng bước, nên tải lại trang vẫn tiếp tục
          đúng câu chưa trả lời.
        </p>
        <p style={{ marginTop: 10 }}>
          <Link href="/sources" className="link" style={{ fontSize: 15 }}>
            Hoặc tạo khóa học từ tài liệu của bạn
          </Link>
        </p>
      </Card>
    </div>
  );
}
