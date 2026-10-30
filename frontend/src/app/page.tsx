"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchCourses, type CourseList } from "@/lib/api";
import { useAuth, useSessionQueryKey } from "./providers";

export default function HomePage() {
  const { data: user, isLoading } = useAuth();
  const listKey = useSessionQueryKey("courses", { limit: 5 });

  const courses = useQuery({
    queryKey: listKey,
    queryFn: () => fetchCourses(5, 0),
    enabled: !!user,
    retry: false,
  });

  return (
    <div className="container">
      <div className="topbar">
        <h1>AI Learning Platform</h1>
        <span className="badge">
          {isLoading ? "..." : user ? `xin chào, ${user.displayName}` : "chưa đăng nhập"}
        </span>
      </div>

      <div className="card">
        <h2>Học cái gì hôm nay?</h2>
        <p>
          Nhập một chủ đề — trả lời 5 câu phỏng vấn — nhận lộ trình cá nhân hóa
          với bài học và quiz tương tác.
        </p>
        {user ? (
          <Link href="/new">
            <button>Tạo khóa học mới</button>
          </Link>
        ) : (
          <Link href="/login">
            <button>Đăng nhập để bắt đầu</button>
          </Link>
        )}
      </div>

      {user && (
        <div className="card">
          <h3>Khóa học của tôi</h3>
          {courses.isLoading && <p>Đang tải danh sách…</p>}
          {courses.isError && (
            <div className="error-box">
              Không tải được khóa học: {courses.error.message}
              <br />
              <button type="button" style={{ marginTop: 8 }} onClick={() => courses.refetch()}>
                Thử lại
              </button>
            </div>
          )}
          {courses.data && courses.data.items.length === 0 && (
            <p>Bạn chưa có khóa học nào. Hãy tạo khóa học đầu tiên.</p>
          )}
          {courses.data && courses.data.items.length > 0 && (
            <ul className="course-list">
              {courses.data.items.map((c) => (
                <li key={c.id}>
                  <Link className="link" href={`/course/${c.id}`}>
                    {c.topic}
                  </Link>{" "}
                  <span className="badge">{c.status}</span>{" "}
                  <span className="badge">
                    {c.progress.completed}/{c.progress.total} bài ({c.progress.percent}%)
                  </span>
                  {c.resumeLessonId && (
                    <>
                      {" "}
                      <Link className="link" href={`/lesson/${c.resumeLessonId}`}>
                        Học tiếp
                      </Link>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {courses.data && courses.data.total > courses.data.items.length && (
            <p className="badge">Hiển thị {courses.data.items.length}/{courses.data.total} khóa học</p>
          )}
        </div>
      )}

      <div className="card">
        <h3>Cách hoạt động</h3>
        <ol>
          <li>Nhập chủ đề bạn muốn học</li>
          <li>Trả lời phỏng vấn ngắn (5 câu) để hệ thống hiểu mục tiêu của bạn</li>
          <li>Duyệt đề xuất khóa học (proposal)</li>
          <li>Chờ hệ thống sinh bài học</li>
          <li>Học và làm quiz — điểm được chấm và lưu tự động</li>
        </ol>
      </div>
    </div>
  );
}
