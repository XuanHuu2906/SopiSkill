"use client";

import Link from "next/link";
import { useAuth } from "./providers";

export default function HomePage() {
  const { data: user, isLoading } = useAuth();

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
