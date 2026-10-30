"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, loginRequest, registerRequest } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (mode === "register" && password !== confirm) {
      setError("Mật khẩu nhập lại không khớp.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await loginRequest(email, password);
      } else {
        await registerRequest(email, password);
      }
      router.push("/");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || `Lỗi ${err.status}`);
      } else {
        setError("Không kết nối được máy chủ.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container">
      <div className="card" style={{ maxWidth: 420, margin: "0 auto" }}>
        <h2>{mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}</h2>
        <form onSubmit={submit} className="auth-form">
          <label>
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ban@email.com"
              autoComplete="email"
            />
          </label>
          <label>
            Mật khẩu
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Tối thiểu 8 ký tự"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </label>
          {mode === "register" && (
            <label>
              Nhập lại mật khẩu
              <input
                type="password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </label>
          )}
          {error && <p className="error-text">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? "Đang xử lý..." : mode === "login" ? "Đăng nhập" : "Đăng ký"}
          </button>
        </form>
        <p>
          {mode === "login" ? "Chưa có tài khoản? " : "Đã có tài khoản? "}
          <button
            className="link-btn"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {mode === "login" ? "Đăng ký" : "Đăng nhập"}
          </button>
        </p>
      </div>
    </div>
  );
}
