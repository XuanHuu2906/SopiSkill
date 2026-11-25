"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import {
  ApiError,
  exchangeOAuthToken,
  loginRequest,
  registerRequest,
} from "@/lib/api";
import { useRedirectAfterLogin, useSessionRefresh } from "../providers";
import { useI18n } from "@/components/i18n/I18nProvider";
import LinkAccountSheet from "@/components/auth/LinkAccountSheet";
import { Button } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Field";

function LoginInner() {
  const params = useSearchParams();
  const nextPath = params.get("next") || "/";
  const redirectAfterLogin = useRedirectAfterLogin();
  const refreshSession = useSessionRefresh();
  const { t } = useI18n();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [oauthNotice, setOauthNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [linkPrompt, setLinkPrompt] = useState<{
    provider: string;
    email: string;
    linkTicket: string;
  } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setOauthNotice("");
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

  async function handleOAuthClick(provider: "google" | "apple") {
    setError("");
    setOauthNotice("");
    const idTokenParam = params.get("idToken");
    if (!idTokenParam) {
      setOauthNotice(
        `Đăng nhập ${provider === "google" ? "Google" : "Apple"} cần cấu hình OIDC Client ID trên môi trường production (hiện dùng Email & Mật khẩu ở môi trường cục bộ).`,
      );
      return;
    }
    setBusy(true);
    try {
      await exchangeOAuthToken(provider, idTokenParam);
      await refreshSession();
      redirectAfterLogin(nextPath);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "ACCOUNT_LINK_REQUIRED") {
        const ticket = String(err.details?.linkTicket ?? "");
        const linkedEmail = String(err.details?.email ?? email);
        if (ticket) {
          setLinkPrompt({ provider, email: linkedEmail, linkTicket: ticket });
          return;
        }
      }
      setError(err instanceof ApiError ? err.message : "Đăng nhập OAuth thất bại.");
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

      <div className="oauth-divider" aria-hidden="true">
        <span>{t("login.oauthDivider")}</span>
      </div>

      <div className="oauth-buttons">
        <Button
          type="button"
          variant="secondary"
          size="md"
          block
          disabled={busy}
          onClick={() => void handleOAuthClick("google")}
        >
          {t("login.continueGoogle")}
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="md"
          block
          disabled={busy}
          onClick={() => void handleOAuthClick("apple")}
        >
          {t("login.continueApple")}
        </Button>
      </div>

      {oauthNotice && (
        <p className="notice-box" role="status" style={{ marginTop: 12 }}>
          {oauthNotice}
        </p>
      )}

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

      {linkPrompt && (
        <LinkAccountSheet
          open={true}
          provider={linkPrompt.provider}
          email={linkPrompt.email}
          linkTicket={linkPrompt.linkTicket}
          onLinked={async () => {
            await refreshSession();
            redirectAfterLogin(nextPath);
          }}
          onClose={() => setLinkPrompt(null)}
        />
      )}
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
