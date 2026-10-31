"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";

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

function CurriculumCard({
  skills,
  prerequisites,
}: {
  skills: NonNullable<ProposalOut["payload"]["skills"]>;
  prerequisites: [string, string][];
}) {
  const byId = new Map(skills.map((s) => [s.id, s]));
  return (
    <div className="card">
      <h2>Lộ trình kỹ năng (prerequisite DAG)</h2>
      <p className="muted">
        {skills.length} kỹ năng · {prerequisites.length} liên kết tiên quyết. Bạn học theo
        đúng thứ tự này; mỗi bài gắn một kết quả đo được (Bloom).
      </p>
      <ol className="curriculum-list">
        {skills.map((skill) => {
          const needs = prerequisites
            .filter(([, child]) => child === skill.id)
            .map(([parent]) => byId.get(parent)?.title)
            .filter(Boolean);
          return (
            <li key={skill.id}>
              <strong>{skill.title}</strong>{" "}
              <span className="badge">{skill.bloomLevel}</span>
              {needs.length > 0 && (
                <div className="muted">Cần học trước: {needs.join(", ")}</div>
              )}
            </li>
          );
        })}
      </ol>
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

  if (!courseId) return <div className="container">Thiếu courseId.</div>;
  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated) return <div className="container">Đang chuyển tới trang đăng nhập…</div>;
  if (proposal.isError)
    return (
      <div className="container">
        <div className="error-box">Không tải được đề xuất: {proposal.error.message}</div>
        <button onClick={() => proposal.refetch()}>Thử lại</button>
      </div>
    );

  return (
    <div className="container">
      <h1>Đề xuất khóa học</h1>
      {proposal.isLoading && <div className="card">Đang tải proposal...</div>}
      {proposal.data && (
        <>
          <div className="card">
            <h2>{proposal.data.payload.name}</h2>
            <p>{proposal.data.payload.objective}</p>
            {proposal.data.payload.learnerProfile && (
              <div className="profile-box">
                <h3>Hồ sơ học viên (suy ra từ câu trả lời của bạn)</h3>
                <p>
                  <span className="badge">
                    {LEVEL_LABEL[proposal.data.payload.learnerProfile.currentLevel] ??
                      proposal.data.payload.learnerProfile.currentLevel}
                  </span>
                  <span className="badge">
                    Độ sâu:{" "}
                    {DEPTH_LABEL[proposal.data.payload.learnerProfile.depth] ??
                      proposal.data.payload.learnerProfile.depth}
                  </span>
                  <span className="badge">
                    {proposal.data.payload.learnerProfile.weeklyMinutes != null
                      ? `${Math.round(
                          proposal.data.payload.learnerProfile.weeklyMinutes / 60
                        )} giờ/tuần`
                      : "Chưa nêu thời gian/tuần"}
                  </span>
                  {proposal.data.payload.learnerProfile.preferredStyles.map((style) => (
                    <span className="badge" key={style}>
                      {STYLE_LABEL[style] ?? style}
                    </span>
                  ))}
                </p>
                {proposal.data.payload.learnerProfile.goal && (
                  <p className="muted">
                    Mục tiêu: {proposal.data.payload.learnerProfile.goal}
                  </p>
                )}
                {proposal.data.payload.learnerProfile.warnings.map((warning, i) => (
                  <p className="muted" key={i}>
                    Lưu ý: {warning}
                  </p>
                ))}
              </div>
            )}
            <p>
              <strong>Kết quả mong đợi:</strong>
            </p>
            <ul>
              {proposal.data.payload.outcomes.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          </div>
          {proposal.data.payload.skills && proposal.data.payload.skills.length > 0 && (
            <CurriculumCard
              skills={proposal.data.payload.skills}
              prerequisites={proposal.data.payload.prerequisites ?? []}
            />
          )}
          {proposal.data.payload.units.map((u, i) => (
            <div className="card" key={i}>
              <h3>{u.title}</h3>
              <p>{u.blurb}</p>
              <ol>
                {u.lessonTitles.map((l, j) => (
                  <li key={j}>{l}</li>
                ))}
              </ol>
            </div>
          ))}
          {proposal.data.approved && (
            <div className="success-box">
              Đề xuất này đã được duyệt (version {proposal.data.version}).
            </div>
          )}
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          <button
            type="button"
            onClick={approve}
            disabled={approving || proposal.data.approved}
          >
            {proposal.data.approved
              ? "Đã duyệt"
              : approving
                ? "Đang duyệt..."
                : "Duyệt & sinh khóa học"}
          </button>
        </>
      )}
    </div>
  );
}

export default function ProposalPage() {
  return (
    <Suspense fallback={<div className="container">Đang tải...</div>}>
      <ProposalInner />
    </Suspense>
  );
}
