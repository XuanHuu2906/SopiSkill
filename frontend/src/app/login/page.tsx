"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError, loginRequest, registerRequest } from "@/lib/api";
import { useRedirectAfterLogin, useSessionRefresh } from "../providers";

function LoginInner() {
  const params = useSearchParams();
  const nextPath = params.get("next") || "/";
  const redirectAfterLogin = useRedirectAfterLogin();
  const refreshSession = useSessionRefresh();
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
      await refreshSession();
      redirectAfterLogin(nextPath);
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
        {nextPath !== "/" && (
          <p className="badge">Bạn cần đăng nhập để tiếp tục.</p>
        )}
        <h2>{mode === "login" ? "Đăng nhập" : "Tạo tài khoản"}</h2>
        <form onSubmit={submit} className="auth-form">
          <label htmlFor="login-email">
            Email
            <input
              id="login-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ban@email.com"
              autoComplete="email"
            />
          </label>
          <label htmlFor="login-password">
            Mật khẩu
            <input
              id="login-password"
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
            <label htmlFor="login-password-confirm">
              Nhập lại mật khẩu
              <input
                id="login-password-confirm"
                type="password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </label>
          )}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Đang xử lý..." : mode === "login" ? "Đăng nhập" : "Đăng ký"}
          </button>
        </form>
        <p>
          {mode === "login" ? "Chưa có tài khoản? " : "Đã có tài khoản? "}
          <button
            type="button"
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

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="container">Đang tải...</div>}>
      <LoginInner />
    </Suspense>
  );
}
