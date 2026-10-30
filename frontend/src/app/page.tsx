"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getUserId } from "@/lib/api";

export default function HomePage() {
  return (
    <div className="container">
      <div className="topbar">
        <h1>AI Learning Platform</h1>
        <span className="badge">user: {getUserId()}</span>
      </div>

      <div className="card">
        <h2>Học cái gì hôm nay?</h2>
        <p>
          Nhập một chủ đề — trả lời 5 câu phỏng vấn — nhận lộ trình cá nhân hóa
          với bài học và quiz tương tác.
        </p>
        <Link href="/new">
          <button>Tạo khóa học mới</button>
        </Link>
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
