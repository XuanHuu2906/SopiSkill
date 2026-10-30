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
  };
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
            <p>
              <strong>Kết quả mong đợi:</strong>
            </p>
            <ul>
              {proposal.data.payload.outcomes.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          </div>
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
