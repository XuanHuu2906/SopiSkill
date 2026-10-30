"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

interface CourseDetail {
  id: string;
  topic: string;
  status: string;
  units: {
    id: string;
    orderIndex: number;
    title: string;
    blurb: string;
    lessons: {
      id: string;
      orderIndex: number;
      title: string;
      status: string;
      contentVersion: number;
    }[];
  }[];
  progress: { completed: number; total: number; percent: number };
}

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();

  const course = useQuery({
    queryKey: ["course", courseId],
    queryFn: () => api<CourseDetail>(`/v1/courses/${courseId}`),
    enabled: !!courseId,
    refetchInterval: (q) =>
      q.state.data && ["ready", "failed"].includes(q.state.data.status) ? false : 2000,
  });

  if (!courseId) return <div className="container">Thiếu courseId.</div>;

  return (
    <div className="container">
      <div className="topbar">
        <h1>{course.data?.topic ?? "Khóa học"}</h1>
        <Link href="/" className="link">
          ← Trang chủ
        </Link>
      </div>

      {course.data?.status === "failed" && (
        <div className="error-box">
          Sinh khóa học thất bại.
          <br />
          <button
            style={{ marginTop: 8 }}
            onClick={() => api(`/v1/courses/${courseId}/retry`, { method: "POST" })}
          >
            Thử lại
          </button>
        </div>
      )}

      {course.data?.units.map((unit) => (
        <div key={unit.id}>
          <h2>{unit.title}</h2>
          <div className="card">
            <p>{unit.blurb}</p>
            {unit.lessons.map((lesson) => (
              <div key={lesson.id} style={{ margin: "8px 0" }}>
                <Link className="link" href={`/lesson/${lesson.id}`}>
                  {lesson.orderIndex + 1}. {lesson.title}
                </Link>{" "}
                <span className="badge">{lesson.status}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
