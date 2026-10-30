"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";

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
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const proposal = useQuery({
    queryKey: ["proposal", courseId],
    queryFn: () => api<ProposalOut>(`/v1/courses/${courseId}/proposal`),
    enabled: !!courseId,
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
          {error && <div className="error-box">{error}</div>}
          <button onClick={approve} disabled={approving}>
            {approving ? "Đang duyệt..." : "Duyệt & sinh khóa học"}
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
