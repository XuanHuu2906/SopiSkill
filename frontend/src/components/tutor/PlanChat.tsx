"use client";

import { useState } from "react";
import { newClientId, streamTutorMessage } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export interface RevisedProposalEvent {
  version: number;
  approved: boolean;
  payload: {
    name: string;
    objective: string;
    units: { title: string; blurb: string; lessonTitles: string[] }[];
    outcomes: string[];
  };
}

const PLAN_CHIPS = [
  "Thêm bài dự án thực hành",
  "Rút gọn kế hoạch học nhanh hơn",
  "Bổ sung ví dụ thực tế vào chương cuối",
];

/**
 * Embedded `PlanChat` on `/new/proposal`: asks Sopi (`entryPoint='proposal'`) to revise the
 * course outline via `revise_proposal`, sliding the live ProposalCard to `version + 1`.
 */
export default function PlanChat({
  courseId,
  disabled = false,
  onProposalRevised,
}: {
  courseId: string;
  disabled?: boolean;
  onProposalRevised: (revised: RevisedProposalEvent) => void;
}) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function ask(override?: string) {
    const prompt = (override ?? input).trim();
    if (!prompt || streaming || disabled) return;
    setStreaming(true);
    setError(null);
    setReply("");
    if (!override) setInput("");

    try {
      await streamTutorMessage(
        courseId,
        {
          clientMessageId: newClientId("pchat"),
          threadId,
          text: prompt,
          entryPoint: "proposal",
          contextLabel: "Chỉnh đề cương cùng Sopi",
          threadKind: "task",
        },
        {
          onThreadId: (tid) => setThreadId(tid),
          onEvent: (evt) => {
            if (evt.event === "delta" && evt.data.text) {
              setReply((prev) => prev + evt.data.text);
            } else if (evt.event === "proposal_revised" && evt.data.version && evt.data.payload) {
              onProposalRevised({
                version: evt.data.version,
                approved: Boolean(evt.data.approved),
                payload: evt.data.payload as unknown as RevisedProposalEvent["payload"],
              });
            } else if (evt.event === "error") {
              setError(evt.data.message ?? "Sopi không thể chỉnh đề cương lúc này.");
            }
          },
        }
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không gửi được yêu cầu chỉnh đề cương.");
    } finally {
      setStreaming(false);
    }
  }

  return (
    <Card variant="tint" style={{ marginTop: 18 }}>
      <span className="eyebrow">Hỏi Sopi chỉnh đề cương</span>
      <p className="caption" style={{ margin: "4px 0 10px" }}>
        Muốn thêm bài thực hành hoặc rút gọn lộ trình? Nhắn trực tiếp để Sopi cập nhật đề xuất.
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {PLAN_CHIPS.map((chip) => (
          <button
            key={chip}
            type="button"
            className="quick-chip"
            disabled={streaming || disabled}
            onClick={() => void ask(chip)}
          >
            {chip}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
        style={{ display: "flex", gap: 8, alignItems: "center" }}
      >
        <label htmlFor="plan-chat-input" className="sr-only">
          Yêu cầu Sopi chỉnh đề cương
        </label>
        <input
          id="plan-chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ví dụ: Thêm bài thực hành ở chương cuối…"
          disabled={streaming || disabled}
          style={{ flex: 1 }}
        />
        <Button type="submit" size="sm" disabled={streaming || disabled || !input.trim()}>
          {streaming ? "Đang chỉnh…" : "Gửi Sopi"}
        </Button>
      </form>

      {reply && (
        <p style={{ marginTop: 10, fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.5 }} role="status">
          <strong>Sopi:</strong> {reply}
        </p>
      )}
      {error && (
        <div className="error-box" role="alert" style={{ marginTop: 10 }}>
          {error}
        </div>
      )}
    </Card>
  );
}
