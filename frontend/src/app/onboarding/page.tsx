"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, saveOnboarding } from "@/lib/api";
import { useRequireAuth } from "../providers";
import { useI18n } from "@/components/i18n/I18nProvider";
import { AvatarBadge, AVATAR_OPTIONS, type AvatarId } from "@/components/auth/AvatarSheet";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/Progress";

const ROLE_CHOICES = [
  "Sinh viên / Học sinh",
  "Kỹ sư phần mềm",
  "Sản phẩm & Thiết kế",
  "Kinh doanh & Marketing",
  "Nghiên cứu & Giảng dạy",
  "Tự học chuyển ngành",
];

const TOPIC_CHOICES = [
  "AI & Machine Learning",
  "Lập trình & Hệ thống",
  "Khoa học dữ liệu",
  "Toán & Xác suất",
  "Thiết kế & UX",
  "Kinh tế & Tài chính",
  "Ngoại ngữ",
  "Kỹ năng viết & tư duy",
];

const STYLE_CHOICES = [
  "Ví dụ thực tế & dự án nhỏ",
  "Sơ đồ trực quan & công thức",
  "Luyện tập nhanh & câu hỏi tình huống",
  "Đào sâu nguyên lý từ gốc",
];

const GOAL_CHOICES = [
  "Nắm nền tảng trong 1 tuần",
  "Ứng dụng vào công việc ngay",
  "Ôn thi / Phỏng vấn kỹ thuật",
  "Duy trì thói quen 10 phút mỗi ngày",
];

function toggleItem(list: string[], item: string): string[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

export default function OnboardingPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const { t, lessonLanguage, setLessonLanguage } = useI18n();

  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [roles, setRoles] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [learningStyles, setLearningStyles] = useState<string[]>([]);
  const [goals, setGoals] = useState<string[]>([]);
  const [avatar, setAvatar] = useState<AvatarId>((user?.avatar as AvatarId) ?? "happy");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const canProceed =
    (step === 1 && roles.length > 0) ||
    (step === 2 && topics.length > 0) ||
    (step === 3 && learningStyles.length > 0) ||
    (step === 4 && goals.length > 0);

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await saveOnboarding({
        roles,
        topics,
        learningStyles,
        goals,
        avatar,
        lessonLanguage,
      });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không thể lưu hồ sơ onboarding.");
      setBusy(false);
    }
  }

  return (
    <div className="onboarding-page" data-testid="onboarding-page">
      <header style={{ marginBottom: 20 }}>
        <span className="eyebrow">{t("onboarding.eyebrow")}</span>
        <h1 className="page-title" style={{ margin: "4px 0 8px" }}>
          {t("onboarding.title")}
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <ProgressBar percent={step * 25} label={`Tiến độ thiết lập bước ${step}/4`} />
          <span className="caption" style={{ whiteSpace: "nowrap" }}>
            {t("onboarding.stepOf", { step })}
          </span>
        </div>
      </header>

      <Card>
        {step === 1 && (
          <div>
            <h2 className="section-title" style={{ marginTop: 0 }}>
              1. Vai trò hiện tại của bạn?
            </h2>
            <div className="onboarding-chip-grid">
              {ROLE_CHOICES.map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`onboarding-chip${roles.includes(r) ? " is-selected" : ""}`}
                  aria-pressed={roles.includes(r)}
                  onClick={() => setRoles((prev) => toggleItem(prev, r))}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 className="section-title" style={{ marginTop: 0 }}>
              2. Bạn quan tâm những chủ đề nào?
            </h2>
            <div className="onboarding-chip-grid">
              {TOPIC_CHOICES.map((tp) => (
                <button
                  key={tp}
                  type="button"
                  className={`onboarding-chip${topics.includes(tp) ? " is-selected" : ""}`}
                  aria-pressed={topics.includes(tp)}
                  onClick={() => setTopics((prev) => toggleItem(prev, tp))}
                >
                  {tp}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h2 className="section-title" style={{ marginTop: 0 }}>
              3. Bạn thích học theo phong cách nào?
            </h2>
            <div className="onboarding-chip-grid">
              {STYLE_CHOICES.map((st) => (
                <button
                  key={st}
                  type="button"
                  className={`onboarding-chip${learningStyles.includes(st) ? " is-selected" : ""}`}
                  aria-pressed={learningStyles.includes(st)}
                  onClick={() => setLearningStyles((prev) => toggleItem(prev, st))}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 4 && (
          <div>
            <h2 className="section-title" style={{ marginTop: 0 }}>
              4. Mục tiêu học tập & Phong cách cá nhân
            </h2>
            <div className="onboarding-chip-grid" style={{ marginBottom: 20 }}>
              {GOAL_CHOICES.map((g) => (
                <button
                  key={g}
                  type="button"
                  className={`onboarding-chip${goals.includes(g) ? " is-selected" : ""}`}
                  aria-pressed={goals.includes(g)}
                  onClick={() => setGoals((prev) => toggleItem(prev, g))}
                >
                  {g}
                </button>
              ))}
            </div>

            <div style={{ marginTop: 18 }}>
              <span className="eyebrow" style={{ display: "block", marginBottom: 8 }}>
                Ảnh đại diện Sopi
              </span>
              <div className="avatar-grid">
                {AVATAR_OPTIONS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className={`avatar-option${avatar === opt.id ? " is-active" : ""}`}
                    aria-pressed={avatar === opt.id}
                    onClick={() => setAvatar(opt.id)}
                  >
                    <AvatarBadge avatar={opt.id} initial="S" size={40} />
                    <span>{opt.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 18 }}>
              <label htmlFor="onboarding-lesson-lang" className="eyebrow" style={{ display: "block", marginBottom: 6 }}>
                Ngôn ngữ bài học mặc định
              </label>
              <select
                id="onboarding-lesson-lang"
                value={lessonLanguage === "en" ? "en" : "vi"}
                onChange={(e) => setLessonLanguage(e.target.value as "vi" | "en")}
              >
                <option value="vi">Tiếng Việt</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>
        )}

        {error && (
          <div className="error-box" role="alert" style={{ marginTop: 14 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 22, gap: 12 }}>
          <Button
            variant="secondary"
            size="md"
            disabled={step === 1 || busy}
            onClick={() => setStep((s) => (s > 1 ? ((s - 1) as 1 | 2 | 3 | 4) : s))}
          >
            {t("onboarding.back")}
          </Button>
          {step < 4 ? (
            <Button
              size="md"
              disabled={!canProceed}
              onClick={() => setStep((s) => (s < 4 ? ((s + 1) as 1 | 2 | 3 | 4) : s))}
            >
              {t("onboarding.next")}
            </Button>
          ) : (
            <Button size="md" disabled={!canProceed || busy} onClick={() => void finish()}>
              {busy ? "Đang lưu…" : t("onboarding.finish")}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
