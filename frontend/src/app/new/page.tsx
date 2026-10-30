"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, newClientId } from "@/lib/api";

interface CourseOut {
  id: string;
  topic: string;
  status: string;
}

export default function NewCoursePage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    if (!topic.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const course = await api<CourseOut>("/v1/courses", {
        method: "POST",
        body: { topic: topic.trim(), clientCourseId: newClientId("cc") },
      });
      router.push(`/new/interview?courseId=${encodeURIComponent(course.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container">
      <div className="topbar">
        <h1>Tạo khóa học mới</h1>
      </div>

      <div className="card">
        <h2>Bạn muốn học gì?</h2>
        <p>Nhập một chủ đề — hệ thống sẽ phỏng vấn bạn rồi đề xuất lộ trình.</p>
        <input
          type="text"
          placeholder="Ví dụ: Python cho người mới"
          value={topic}
          maxLength={200}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && start()}
        />
        {error && <div className="error-box">{error}</div>}
        <div style={{ marginTop: 12 }}>
          <button onClick={start} disabled={loading || !topic.trim()}>
            {loading ? "Đang tạo..." : "Bắt đầu"}
          </button>
        </div>
      </div>
    </div>
  );
}
