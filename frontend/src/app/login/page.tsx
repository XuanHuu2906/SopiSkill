"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError, loginRequest, registerRequest } from "@/lib/api";
import { useRedirectAfterLogin, useSessionRefresh } from "../providers";
import { Button } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Field";

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

  const isLogin = mode === "login";

  return (
    <div style={{ width: "100%" }}>
      <span className="eyebrow" style={{ display: "block", textAlign: "center" }}>
        SopiSkill
      </span>
      <h1 className="hero-title" style={{ textAlign: "center", margin: "8px 0 12px" }}>
        Học bất cứ điều gì.
      </h1>
      <p
        className="lede"
        style={{ textAlign: "center", maxWidth: 360, margin: "0 auto 28px" }}
      >
        Nói cho hệ thống biết bạn tò mò điều gì, nhận về một khóa học ngắn gọn, có bài
        giảng và quiz — rồi quay lại bất cứ lúc nào.
      </p>

      {nextPath !== "/" && (
        <p className="notice-box" style={{ marginTop: 0 }}>
          Bạn cần đăng nhập để tiếp tục.
        </p>
      )}

      <form onSubmit={submit} className="auth-form" noValidate>
        <TextInput
          id="login-email"
          label="Email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="ban@email.com"
          autoComplete="email"
        />
        <TextInput
          id="login-password"
          label="Mật khẩu"
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Tối thiểu 8 ký tự"
          autoComplete={isLogin ? "current-password" : "new-password"}
        />
        {mode === "register" && (
          <TextInput
            id="login-password-confirm"
            label="Nhập lại mật khẩu"
            type="password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" block disabled={busy}>
          {busy ? "Đang xử lý..." : isLogin ? "Đăng nhập" : "Tạo tài khoản"}
        </Button>
      </form>

      <p style={{ textAlign: "center", marginTop: 16 }} className="muted">
        {isLogin ? "Chưa có tài khoản? " : "Đã có tài khoản? "}
        <button
          type="button"
          className="link-btn"
          onClick={() => {
            setMode(isLogin ? "register" : "login");
            setError("");
          }}
        >
          {isLogin ? "Đăng ký" : "Đăng nhập"}
        </button>
      </p>

      <p className="caption" style={{ textAlign: "center", marginTop: 28 }}>
        Nội dung bạn nhập được xử lý trên máy chủ của SopiSkill và chỉ dùng để tạo khóa
        học cho chính bạn.
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div style={{ padding: 24, textAlign: "center" }} className="muted">
          Đang tải...
        </div>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
