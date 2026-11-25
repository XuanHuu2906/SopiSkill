"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, updateProposal } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import PlanChat from "@/components/tutor/PlanChat";

interface ProposalUnit {
  title: string;
  blurb: string;
  lessonTitles: string[];
}

interface ProposalOut {
  version: number;
  approved: boolean;
  payload: {
    name: string;
    objective: string;
    units: ProposalUnit[];
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
  const queryClient = useQueryClient();
  const courseId = params.get("courseId") ?? "";
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const proposalKey = useSessionQueryKey("proposal", courseId);
  const [approving, setApproving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftObjective, setDraftObjective] = useState("");
  const [draftOutcomesText, setDraftOutcomesText] = useState("");
  const [draftUnits, setDraftUnits] = useState<ProposalUnit[]>([]);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [previousDrafts, setPreviousDrafts] = useState<ProposalOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  const proposal = useQuery({
    queryKey: proposalKey,
    queryFn: () => api<ProposalOut>(`/v1/courses/${courseId}/proposal`),
    enabled: !!courseId && isAuthenticated,
  });

  function startEdit() {
    if (!proposal.data) return;
    const p = proposal.data.payload;
    setDraftName(p.name);
    setDraftObjective(p.objective);
    setDraftOutcomesText(p.outcomes.join("\n"));
    setDraftUnits(p.units.map((u) => ({ title: u.title, blurb: u.blurb, lessonTitles: [...u.lessonTitles] })));
    setError(null);
    setSaveMessage(null);
    setEditing(true);
  }

  async function saveEdit() {
    if (!proposal.data) return;
    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const updated = await updateProposal<ProposalOut>(courseId, {
        expectedVersion: proposal.data.version,
        name: draftName.trim(),
        objective: draftObjective.trim(),
        outcomes: draftOutcomesText
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        units: draftUnits.map((u) => ({
          title: u.title.trim(),
          blurb: u.blurb.trim(),
          lessonTitles: u.lessonTitles.map((t) => t.trim()).filter(Boolean),
        })),
      });
      queryClient.setQueryData(proposalKey, updated);
      setEditing(false);
      setSaveMessage(`Đã lưu đề xuất phiên bản ${updated.version}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được thay đổi.");
    } finally {
      setSaving(false);
    }
  }

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
          <div className="flow-header-meta">
            Phiên bản {proposal.data.version} · Xem lại trước khi tạo
          </div>
        </div>
        {!proposal.data.approved && !editing ? (
          <Button variant="secondary" size="sm" onClick={startEdit}>
            Chỉnh sửa
          </Button>
        ) : (
          <span style={{ width: 40 }} aria-hidden="true" />
        )}
      </div>

      {saveMessage && <div className="success-box">{saveMessage}</div>}
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      {editing ? (
        <Card>
          <span className="eyebrow">Chỉnh sửa kế hoạch (v{proposal.data.version})</span>
          <div style={{ display: "grid", gap: 14, marginTop: 12 }}>
            <div>
              <label htmlFor="proposal-name" className="caption">
                Tên khóa học
              </label>
              <input
                id="proposal-name"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                maxLength={200}
              />
            </div>
            <div>
              <label htmlFor="proposal-objective" className="caption">
                Mục tiêu khóa học
              </label>
              <textarea
                id="proposal-objective"
                rows={3}
                value={draftObjective}
                onChange={(e) => setDraftObjective(e.target.value)}
                maxLength={500}
              />
            </div>
            <div>
              <label htmlFor="proposal-outcomes" className="caption">
                Kết quả đầu ra (mỗi dòng 1 mục tiêu)
              </label>
              <textarea
                id="proposal-outcomes"
                rows={3}
                value={draftOutcomesText}
                onChange={(e) => setDraftOutcomesText(e.target.value)}
              />
            </div>

            {draftUnits.map((unit, uIdx) => (
              <div
                key={uIdx}
                style={{
                  border: "1px solid var(--linen)",
                  borderRadius: "var(--radius-md)",
                  padding: 14,
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="eyebrow">Chương {uIdx + 1}</span>
                  {draftUnits.length > 1 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDraftUnits((prev) => prev.filter((_, idx) => idx !== uIdx))}
                    >
                      Xóa chương
                    </Button>
                  )}
                </div>
                <input
                  aria-label={`Tiêu đề chương ${uIdx + 1}`}
                  value={unit.title}
                  onChange={(e) =>
                    setDraftUnits((prev) =>
                      prev.map((item, idx) => (idx === uIdx ? { ...item, title: e.target.value } : item))
                    )
                  }
                  placeholder="Tiêu đề chương"
                />
                <input
                  aria-label={`Mô tả chương ${uIdx + 1}`}
                  value={unit.blurb}
                  onChange={(e) =>
                    setDraftUnits((prev) =>
                      prev.map((item, idx) => (idx === uIdx ? { ...item, blurb: e.target.value } : item))
                    )
                  }
                  placeholder="Mô tả ngắn chương"
                />
                {unit.lessonTitles.map((lt, lIdx) => (
                  <div key={lIdx} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <input
                      aria-label={`Bài ${lIdx + 1} của chương ${uIdx + 1}`}
                      value={lt}
                      onChange={(e) =>
                        setDraftUnits((prev) =>
                          prev.map((item, idx) =>
                            idx === uIdx
                              ? {
                                  ...item,
                                  lessonTitles: item.lessonTitles.map((t, j) =>
                                    j === lIdx ? e.target.value : t
                                  ),
                                }
                              : item
                          )
                        )
                      }
                    />
                    {unit.lessonTitles.length > 1 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setDraftUnits((prev) =>
                            prev.map((item, idx) =>
                              idx === uIdx
                                ? {
                                    ...item,
                                    lessonTitles: item.lessonTitles.filter((_, j) => j !== lIdx),
                                  }
                                : item
                            )
                          )
                        }
                      >
                        Xóa
                      </Button>
                    )}
                  </div>
                ))}
                <div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      setDraftUnits((prev) =>
                        prev.map((item, idx) =>
                          idx === uIdx
                            ? { ...item, lessonTitles: [...item.lessonTitles, "Bài học mới"] }
                            : item
                        )
                      )
                    }
                  >
                    + Thêm bài
                  </Button>
                </div>
              </div>
            ))}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  setDraftUnits((prev) => [
                    ...prev,
                    { title: `Chương ${prev.length + 1}`, blurb: "Mở rộng thực hành", lessonTitles: ["Bài mới"] },
                  ])
                }
              >
                + Thêm chương
              </Button>
              <span style={{ flex: 1 }} />
              <Button variant="ghost" onClick={() => setEditing(false)} disabled={saving}>
                Hủy
              </Button>
              <Button onClick={() => void saveEdit()} disabled={saving}>
                {saving ? "Đang lưu…" : "Lưu thay đổi"}
              </Button>
            </div>
          </div>
        </Card>
      ) : (
        <>
          <div className="proposal-card">
            <div>
              <span className="eyebrow">Kế hoạch của bạn</span>
              <h1 className="section-title" style={{ margin: "6px 0 8px" }}>
                {payload.name}
              </h1>
              <p className="muted">{payload.objective}</p>
            </div>

            <PlanStats
              units={payload.units.length}
              lessons={lessonCount}
              weeklyMinutes={profile?.weeklyMinutes ?? null}
            />

            {profile && (
              <div className="profile-box" style={{ marginTop: 0 }}>
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

            <div>
              <span className="eyebrow" style={{ color: "var(--ink-3)" }}>
                Học xong, bạn sẽ có thể
              </span>
              <div style={{ marginTop: 10 }}>
                {payload.outcomes.map((outcome, i) => (
                  <div className="outcome-row" key={i}>
                    <span className="outcome-check" aria-hidden="true">
                      <Icon name="checkCircle" size={20} />
                    </span>
                    <span>{outcome}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

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

          {previousDrafts.length > 0 && (
            <details
              className="course-disclosure"
              style={{ marginTop: 14 }}
              data-previous-drafts="true"
            >
              <summary>
                <span>Bản nháp trước ({previousDrafts.length})</span>
                <Icon name="chevronDown" size={18} />
              </summary>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {previousDrafts.map((draft) => (
                  <div
                    key={draft.version}
                    style={{
                      padding: 12,
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--linen)",
                      background: "var(--surface)",
                    }}
                  >
                    <div className="caption" style={{ fontWeight: 700 }}>
                      Phiên bản {draft.version} — {draft.payload.name}
                    </div>
                    <p className="caption" style={{ marginTop: 4 }}>
                      {draft.payload.objective}
                    </p>
                  </div>
                ))}
              </div>
            </details>
          )}

          {!proposal.data.approved && (
            <PlanChat
              courseId={courseId}
              disabled={approving}
              onProposalRevised={(revised) => {
                if (proposal.data) {
                  setPreviousDrafts((prev) => [proposal.data!, ...prev]);
                }
                const nextOut: ProposalOut = {
                  version: revised.version,
                  approved: revised.approved,
                  payload: {
                    ...(proposal.data?.payload ?? {}),
                    ...revised.payload,
                  },
                };
                queryClient.setQueryData(proposalKey, nextOut);
                setSaveMessage(`Sopi đã cập nhật đề xuất lên phiên bản ${revised.version}.`);
              }}
            />
          )}
        </>
      )}

      {proposal.data.approved && (
        <div className="success-box">
          Đề xuất này đã được duyệt (phiên bản {proposal.data.version}).
        </div>
      )}

      {!editing && (
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
      )}
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
