"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";

interface ProposalOut {
  version: number;
  approved: boolean;
  payload: {
    name: string;
    objective: string;
    units: { title: string; blurb: string; lessonTitles: string[] }[];
    outcomes: string[];
    learnerProfile?: {
      goal: string;
      currentLevel: "beginner" | "intermediate" | "advanced";
      weeklyMinutes: number | null;
      preferredStyles: string[];
      depth: "broad" | "balanced" | "deep";
      warnings: string[];
    } | null;
    skills?: {
      id: string;
      title: string;
      lesson: string;
      bloomLevel: string;
      outcome: string;
    }[];
    prerequisites?: [string, string][];
  };
}

const LEVEL_LABEL: Record<string, string> = {
  beginner: "Mới bắt đầu",
  intermediate: "Đã có nền tảng",
  advanced: "Nâng cao",
};

const DEPTH_LABEL: Record<string, string> = {
  broad: "Phủ rộng",
  balanced: "Cân bằng",
  deep: "Đi sâu",
};

const STYLE_LABEL: Record<string, string> = {
  hands_on: "Thực hành",
  project: "Dự án",
  theory: "Lý thuyết",
  visual: "Trực quan",
};

function PlanStats({
  units,
  lessons,
  weeklyMinutes,
}: {
  units: number;
  lessons: number;
  weeklyMinutes: number | null;
}) {
  return (
    <div className="stat-strip">
      <div className="stat-item">
        <div className="stat-value">{lessons}</div>
        <div className="stat-caption">bài học</div>
      </div>
      <div className="stat-item">
        <div className="stat-value">{units}</div>
        <div className="stat-caption">chương</div>
      </div>
      <div className="stat-item">
        <div className="stat-value">
          {weeklyMinutes != null ? Math.max(1, Math.round(weeklyMinutes / 60)) : "—"}
        </div>
        <div className="stat-caption">
          {weeklyMinutes != null ? "giờ mỗi tuần" : "chưa nêu thời gian"}
        </div>
      </div>
    </div>
  );
}

function ProposalInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const proposalKey = useSessionQueryKey("proposal", courseId);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const proposal = useQuery({
    queryKey: proposalKey,
    queryFn: () => api<ProposalOut>(`/v1/courses/${courseId}/proposal`),
    enabled: !!courseId && isAuthenticated,
  });

  async function approve() {
    setApproving(true);
    setError(null);
    try {
      await api(`/v1/courses/${courseId}/approve`, { method: "POST" });
      router.push(`/new/generating?courseId=${encodeURIComponent(courseId)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
      setApproving(false);
    }
  }

  if (!courseId)
    return (
      <div style={{ maxWidth: 680, margin: "0 auto", paddingTop: 40, textAlign: "center" }}>
        <h1 className="section-title" style={{ marginBottom: 8 }}>
          Chưa có kế hoạch học
        </h1>
        <p className="lede">Hãy bắt đầu từ trang tạo khóa học để xem đề xuất.</p>
        <Button variant="secondary" onClick={() => router.push("/new")}>
          Về trang tạo khóa học
        </Button>
      </div>
    );
  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;
  if (proposal.isError)
    return (
      <div>
        <div className="error-box" role="alert">
          Không tải được đề xuất: {proposal.error.message}
        </div>
        <Button variant="secondary" onClick={() => proposal.refetch()}>
          Thử lại
        </Button>
      </div>
    );

  if (proposal.isLoading) return <p className="muted">Đang tải đề xuất…</p>;
  if (!proposal.data) return null;

  const payload = proposal.data.payload;
  const lessonCount = payload.units.reduce((sum, u) => sum + u.lessonTitles.length, 0);
  const profile = payload.learnerProfile;

  return (
    <div style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="flow-header">
        <IconButton aria-label="Quay lại" onClick={() => router.push("/new")}>
          <Icon name="arrowLeft" size={20} />
        </IconButton>
        <div style={{ flex: 1, textAlign: "center" }}>
          <div className="flow-header-title">Kế hoạch học đã sẵn sàng</div>
          <div className="flow-header-meta">Xem lại trước khi tạo</div>
        </div>
        <span style={{ width: 40 }} aria-hidden="true" />
      </div>

      <Card>
        <span className="eyebrow">Kế hoạch của bạn</span>
        <h1 className="section-title" style={{ margin: "6px 0 8px" }}>
          {payload.name}
        </h1>
        <p className="muted">{payload.objective}</p>

        <PlanStats
          units={payload.units.length}
          lessons={lessonCount}
          weeklyMinutes={profile?.weeklyMinutes ?? null}
        />

        {profile && (
          <div className="profile-box">
            <h2>Hồ sơ học viên (suy ra từ câu trả lời)</h2>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <Badge>{LEVEL_LABEL[profile.currentLevel] ?? profile.currentLevel}</Badge>
              <Badge>Độ sâu: {DEPTH_LABEL[profile.depth] ?? profile.depth}</Badge>
              {profile.preferredStyles.map((style) => (
                <Badge key={style} tone="muted">
                  {STYLE_LABEL[style] ?? style}
                </Badge>
              ))}
            </div>
            {profile.goal && (
              <p className="muted" style={{ marginTop: 10 }}>
                Mục tiêu: {profile.goal}
              </p>
            )}
            {profile.warnings.map((warning, i) => (
              <p className="caption" key={i} style={{ marginTop: 6 }}>
                Lưu ý: {warning}
              </p>
            ))}
          </div>
        )}

        <div style={{ marginTop: 20 }}>
          <span className="eyebrow" style={{ color: "var(--ink-3)" }}>
            Học xong, bạn sẽ có thể
          </span>
          <div style={{ marginTop: 10 }}>
            {payload.outcomes.map((outcome, i) => (
              <div className="outcome-row" key={i}>
                <span className="summary-index">{i + 1}</span>
                <span>{outcome}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {payload.skills && payload.skills.length > 0 && (
        <Card>
          <h2 className="section-title" style={{ fontSize: 19, marginBottom: 8 }}>
            Lộ trình kỹ năng
          </h2>
          <p className="muted">
            {payload.skills.length} kỹ năng · {payload.prerequisites?.length ?? 0} liên kết
            tiên quyết.
          </p>
          <ol className="curriculum-list">
            {payload.skills.map((skill) => {
              const needs = (payload.prerequisites ?? [])
                .filter(([, child]) => child === skill.id)
                .map(([parent]) => payload.skills?.find((s) => s.id === parent)?.title)
                .filter(Boolean);
              return (
                <li key={skill.id}>
                  <strong>{skill.title}</strong>{" "}
                  <Badge tone="muted">{skill.bloomLevel}</Badge>
                  {skill.outcome && (
                    <div className="caption" style={{ marginTop: 2 }}>
                      {skill.outcome}
                    </div>
                  )}
                  {needs.length > 0 && (
                    <div className="caption" style={{ marginTop: 2 }}>
                      Cần học trước: {needs.join(", ")}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </Card>
      )}

      {payload.units.map((unit, i) => (
        <Card key={i}>
          <span className="eyebrow" style={{ color: "var(--ink-3)" }}>
            Chương {i + 1}
          </span>
          <h3 className="section-title" style={{ margin: "4px 0 6px" }}>
            {unit.title}
          </h3>
          <p className="muted">{unit.blurb}</p>
          <ol style={{ marginTop: 12, paddingLeft: 20 }}>
            {unit.lessonTitles.map((title, j) => (
              <li key={j} className="muted" style={{ color: "var(--ink-2)" }}>
                {title}
              </li>
            ))}
          </ol>
        </Card>
      ))}

      {proposal.data.approved && (
        <div className="success-box">
          Đề xuất này đã được duyệt (phiên bản {proposal.data.version}).
        </div>
      )}
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      <Button
        size="lg"
        block
        onClick={() => void approve()}
        disabled={approving || proposal.data.approved}
      >
        {proposal.data.approved
          ? "Đã duyệt"
          : approving
            ? "Đang duyệt..."
            : "Tạo khóa học"}
      </Button>
      <p className="caption" style={{ textAlign: "center", marginTop: 12 }}>
        Muốn khác đi? Quay lại và trả lời phỏng vấn theo hướng khác.
      </p>
    </div>
  );
}

export default function ProposalPage() {
  return (
    <Suspense fallback={<p className="muted">Đang tải...</p>}>
      <ProposalInner />
    </Suspense>
  );
}
