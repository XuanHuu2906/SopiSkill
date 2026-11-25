"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchTutorThread,
  fetchTutorThreads,
  fetchTutorUsage,
  newClientId,
  resumeTutorStream,
  stopTutorMessage,
  streamTutorMessage,
  TutorStreamError,
  type GlobalTutorSessionList,
  type TutorAction,
  type TutorCitation,
  type TutorEntryPoint,
  type TutorStreamEvent,
  type TutorThread,
} from "@/lib/api";
import { useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";
import ChangeCard from "@/components/tutor/ChangeCard";

const TOOL_LABELS: Record<string, string> = {
  read_lesson: "Đọc bài học",
  explain_deeper: "Giải thích sâu hơn",
  read_source: "Tra cứu nguồn",
  flag_question: "Gắn cờ câu hỏi",
  revise_proposal: "Chỉnh đề cương",
  regenerate_unit: "Đề xuất viết lại chương",
};

const PROMPT_CHIPS_BY_ENTRY: Record<TutorEntryPoint, string[]> = {
  tab: [
    "Giải thích trong 30 giây",
    "Cho mình một ví dụ thực tế",
    "Phần này quá khó, viết lại chương giúp mình",
    "Báo lỗi câu hỏi này",
  ],
  wrong_answer: [
    "Vì sao đáp án của mình chưa đúng?",
    "Gợi ý từng bước không lộ đáp án",
    "Cho ví dụ tương tự dễ hơn",
    "Báo lỗi câu hỏi này",
  ],
  teach_block: [
    "Giải thích trực quan hơn",
    "Phần này áp dụng ở đâu?",
    "Đối chiếu với nguồn tài liệu",
    "Mình nên lưu ý gì nhất?",
  ],
  term: [
    "Giải thích thuật ngữ này bằng đời thường",
    "Phân biệt với khái niệm dễ nhầm",
    "Cho ví dụ ngắn có thuật ngữ này",
  ],
  path_harder: [
    "Chương này quá khó, viết lại dễ hơn",
    "Chương này quá dễ, tăng độ sâu hơn",
    "Thêm bài tập tình huống thực tế",
  ],
  proposal: [
    "Thêm bài dự án thực hành",
    "Rút gọn kế hoạch học nhanh hơn",
    "Tăng bài tập áp dụng",
  ],
};

interface ToolNote {
  name: string;
  status: "ok" | "failed";
  summary?: string;
  code?: string;
}

interface UnverifiedPointer {
  chunkId: string;
  sourceId: string;
  sourceTitle?: string | null;
  pageNumber?: number | null;
  sectionAnchor?: string | null;
  validationStatus: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "streaming" | "completed" | "failed" | "cancelled";
  errorCode?: string | null;
  citations?: TutorCitation[];
  unverified?: UnverifiedPointer[];
  insufficientEvidence?: boolean;
}

function citationLabel(citation: TutorCitation): string {
  const title = citation.sourceTitle?.trim() || "Tài liệu";
  const page = citation.pageNumber ? `tr.${citation.pageNumber}` : "";
  return [title, page].filter(Boolean).join(" — ");
}

const STATUS_NOTE: Record<string, string> = {
  TUTOR_DISABLED: "Trợ giảng AI chưa được bật trên hệ thống này.",
  TUTOR_CONTEXT_INVALID: "Ngữ cảnh bài học không hợp lệ, hãy tải lại trang.",
  MESSAGE_IN_PROGRESS: "Câu hỏi trước đang được xử lý, hãy chờ hoặc tải lại lịch sử.",
  TUTOR_LIMIT_REACHED: "Bạn đã hết lượt hỏi trợ giảng trong 24 giờ qua.",
  TUTOR_TOKEN_LIMIT_REACHED: "Bạn đã dùng hết hạn mức token trợ giảng trong 24 giờ qua.",
  TUTOR_CONCURRENCY_LIMIT: "Bạn đang có câu trả lời khác đang chạy, hãy đợi hoặc dừng bớt.",
  TUTOR_STOP_NOT_FOUND: "Không tìm thấy câu trả lời để dừng.",
  TUTOR_TIMEOUT: "Hết thời gian chờ câu trả lời.",
  TUTOR_STALE: "Câu trả lời trước bị gián đoạn (server khởi động lại).",
};

export default function TutorPanel({
  courseId,
  lessonId,
  activeBlockIndex,
  blockLabel,
  entryPoint = "tab",
  open,
  onClose,
  docked = false,
  courseOptions,
  onSelectCourse,
  globalSessions,
  onSelectSession,
}: {
  courseId: string;
  lessonId: string;
  activeBlockIndex: number;
  blockLabel?: string;
  entryPoint?: TutorEntryPoint;
  open: boolean;
  onClose: () => void;
  /** True when the viewport is wide enough to dock the rail beside the lesson. */
  docked?: boolean;
  /** Optional course switcher when Sopi is opened globally outside a lesson. */
  courseOptions?: { id: string; topic: string }[];
  onSelectCourse?: (courseId: string) => void;
  globalSessions?: GlobalTutorSessionList;
  onSelectSession?: (courseId: string, threadId: string) => void;
}) {
  const queryClient = useQueryClient();
  const threadsKey = useSessionQueryKey("tutor-threads", courseId);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [actions, setActions] = useState<TutorAction[]>([]);
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const messageIdRef = useRef<string | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const terminalSeenRef = useRef<boolean>(false);
  const [stopping, setStopping] = useState(false);
  const [toolNotes, setToolNotes] = useState<ToolNote[]>([]);

  const threads = useQuery({
    queryKey: threadsKey,
    queryFn: () => fetchTutorThreads(courseId),
    retry: false,
  });

  const usageKey = useSessionQueryKey("tutor-usage", courseId);
  const usage = useQuery({
    queryKey: usageKey,
    queryFn: () => fetchTutorUsage(courseId),
    retry: false,
    staleTime: 30_000,
  });
  const quotaExhausted =
    usage.data?.remaining.messages === 0 || usage.data?.remaining.tokens === 0;

  // Auto-scroll trong vùng chat (không scroll cả trang) — WCAG-friendly.
  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Reset local thread state when switching courses inside the global Sopi sheet.
  useEffect(() => {
    abortRef.current?.abort();
    setThreadId(null);
    setMessages([]);
    setActions([]);
    setToolNotes([]);
    setError(null);
    setNotice(null);
  }, [courseId]);

  const openThread = useCallback(
    async (id: string) => {
      setError(null);
      try {
        const thread: TutorThread = await fetchTutorThread(courseId, id);
        setThreadId(thread.id);
        setNotice(thread.notice);
        setActions(thread.actions ?? []);
        setMessages(
          thread.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            status:
              m.status === "completed"
                ? "completed"
                : m.status === "failed"
                  ? "failed"
                  : m.status === "cancelled"
                    ? "cancelled"
                    : "pending",
            errorCode: m.errorCode,
            citations: m.citations,
            unverified: [],
            insufficientEvidence: m.role === "assistant" && m.citations.length === 0,
          }))
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Không tải được hội thoại.");
      }
    },
    [courseId]
  );

  function handleEvent(event: TutorStreamEvent) {
    if (event.event === "delta") {
      const chunk = event.data.text ?? "";
      const targetId = event.data.messageId ?? messageIdRef.current;
      if (!chunk) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId ? { ...m, content: m.content + chunk } : m
        )
      );
      return;
    }
    if (event.event === "done") {
      terminalSeenRef.current = true;
      const targetId = event.data.messageId ?? messageIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId ? { ...m, status: "completed" } : m
        )
      );
      return;
    }
    if (event.event === "confirm" && event.data.actionId) {
      const nextAction: TutorAction = {
        actionId: event.data.actionId,
        messageId: event.data.messageId,
        toolName: event.data.toolName ?? "regenerate_unit",
        status: (event.data.status as TutorAction["status"]) ?? "pending",
        payload: event.data.payload as TutorAction["payload"],
        preview: event.data.preview,
      };
      setActions((prev) =>
        prev.some((a) => a.actionId === nextAction.actionId) ? prev : [...prev, nextAction]
      );
      return;
    }
    if (event.event === "restarted") {
      terminalSeenRef.current = true;
      const targetId = event.data.messageId ?? messageIdRef.current;
      if (event.data.content) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === targetId
              ? { ...m, content: event.data.content ?? m.content, status: "completed" }
              : m
          )
        );
      }
      return;
    }
    if (event.event === "citations") {
      const targetId = event.data.messageId ?? messageIdRef.current;
      const citations = event.data.citations ?? [];
      const unverified = event.data.unverified ?? [];
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId
            ? {
                ...m,
                citations,
                unverified,
                insufficientEvidence: event.data.insufficientEvidence ?? citations.length === 0,
              }
            : m
        )
      );
      return;
    }
    if (event.event === "tool") {
      setToolNotes((prev) => [
        ...prev,
        {
          name: event.data.name ?? "tool",
          status: event.data.status === "ok" ? "ok" : "failed",
          summary: event.data.summary,
          code: event.data.code,
        },
      ]);
      return;
    }
    if (event.event === "cancelled") {
      terminalSeenRef.current = true;
      const targetId = event.data.messageId ?? messageIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId ? { ...m, status: "cancelled" } : m
        )
      );
      setNotice("Đã dừng theo yêu cầu. Phần trả lời đã nhận được giữ lại.");
      return;
    }
    if (event.event === "error") {
      terminalSeenRef.current = true;
      const code = event.data.code ?? "TUTOR_PROVIDER_ERROR";
      const targetId = event.data.messageId ?? messageIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId
            ? { ...m, status: "failed", errorCode: code }
            : m
        )
      );
      setError(STATUS_NOTE[code] ?? event.data.message ?? "Trợ giảng gặp lỗi.");
    }
    // heartbeat: giữ kết nối, không cần cập nhật UI
  }

  async function send(overrideText?: string) {
    const question = (overrideText ?? text).trim();
    if (!question || streaming) return;
    setError(null);
    const clientMessageId = newClientId("tmsg");
    messageIdRef.current = null;
    lastEventIdRef.current = null;
    terminalSeenRef.current = false;
    setNotice(null);
    setToolNotes([]);
    const localUser: ChatMessage = {
      id: `local-${clientMessageId}`,
      role: "user",
      content: question,
      status: "completed",
    };
    setMessages((prev) => [...prev, localUser]);
    setText("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    let assistantId = `pending-${clientMessageId}`;
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", status: "pending" },
    ]);

    // Header và frame đều có thể mang messageId thật; chỉ đổi placeholder MỘT lần
    // để delta sau đó cập nhật đúng bong bóng.
    function adoptMessageId(realId: string) {
      if (messageIdRef.current === realId) return;
      const previous = assistantId;
      messageIdRef.current = realId;
      assistantId = realId;
      setMessages((prev) =>
        prev.map((m) => (m.id === previous ? { ...m, id: realId } : m))
      );
    }

    try {
      const streamHandlers = {
        signal: controller.signal,
        onThreadId: (id: string) => setThreadId(id),
        onMessageId: adoptMessageId,
        onEventId: (eid: string) => {
          lastEventIdRef.current = eid;
        },
        onEvent: (event: TutorStreamEvent) => {
          if (event.data.messageId) adoptMessageId(event.data.messageId);
          if (event.event === "delta") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, status: "streaming" }
                  : m
              )
            );
          }
          handleEvent(event);
        },
      };

      await streamTutorMessage(
        courseId,
        {
          clientMessageId,
          threadId,
          text: question,
          entryPoint,
          contextLabel: blockLabel,
          contextRef: { lessonId, blockIndex: activeBlockIndex },
        },
        streamHandlers
      );

      // Multi-pod automatic Last-Event-ID resume if connection closed before terminal event
      if (!terminalSeenRef.current && !controller.signal.aborted && messageIdRef.current && lastEventIdRef.current) {
        await resumeTutorStream(courseId, messageIdRef.current, lastEventIdRef.current, streamHandlers);
      }

      queryClient.invalidateQueries({ queryKey: threadsKey });
      queryClient.invalidateQueries({ queryKey: usageKey });
    } catch (err) {
      if (controller.signal.aborted) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, status: "cancelled" } : m
          )
        );
        setError("Bạn đã dừng câu trả lời. Nội dung đã nhận được giữ nguyên.");
      } else if (err instanceof TutorStreamError) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, status: "failed", errorCode: err.code }
              : m
          )
        );
        setError(STATUS_NOTE[err.code] ?? err.message);
      } else {
        setError(err instanceof Error ? err.message : "Không gửi được câu hỏi.");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  async function stop() {
    const target = messageIdRef.current;
    setStopping(true);
    try {
      // Ưu tiên nói với server TRƯỚC khi cắt kết nối: nếu chỉ abort, server chỉ
      // biết client ngắt chứ không biết đây là "dừng có chủ ý".
      if (target) {
        const result = await stopTutorMessage(courseId, target);
        if (result.status === "cancel_requested") {
          setNotice(result.notice ?? "Đã yêu cầu dừng câu trả lời.");
        }
      }
    } catch (err) {
      // Không chặn việc dừng phía client vì lỗi mạng/CSRF.
      setError(err instanceof Error ? err.message : "Không dừng được phía server.");
    } finally {
      abortRef.current?.abort();
      setStopping(false);
    }
  }


  // Focus the composer rather than the close button: the user opened the sheet
  // to type, and starting on "Đóng" makes the first Tab skip the input.
  useModalPanel({
    open,
    onClose,
    panelRef: sheetRef,
    initialFocusSelector: "#tutor-input",
    modal: !docked,
  });

  if (!open) return null;

  return (
    <>
      <button
        type="button"
        className={`tutor-backdrop${docked ? " is-docked" : ""}`}
        aria-label="Đóng Sopi"
        tabIndex={-1}
        onClick={onClose}
      />
      {/* `aside` carries an implicit `complementary` role, and ARIA forbids
          overriding it with `dialog` — axe reports `aria-allowed-role`. A `div`
          is the valid host. The element type stays constant across the dock
          breakpoint so resizing never remounts the panel. */}
      <div
        className={`tutor-sheet${docked ? " is-docked" : ""}`}
        role="dialog"
        aria-modal={docked ? undefined : "true"}
        aria-labelledby="tutor-heading"
        ref={sheetRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="tutor-avatar" aria-hidden="true">
              S
            </span>
            <div>
              <div id="tutor-heading" className="tutor-title">
                Sopi
              </div>
              <div className="tutor-subtitle">
                {blockLabel
                  ? courseOptions
                    ? blockLabel
                    : `${blockLabel} · block ${activeBlockIndex + 1}`
                  : "Trợ giảng AI"}
                {usage.data
                  ? ` · còn ${usage.data.remaining.messages ?? 0}/${usage.data.limits.messagesPerDay} lượt`
                  : ""}
              </div>
            </div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>

        {courseOptions && courseOptions.length > 1 && onSelectCourse && (
          <div className="tutor-threads" style={{ marginBottom: 8 }}>
            <label className="sr-only" htmlFor="tutor-course-select">
              Chọn khóa học để hỏi Sopi
            </label>
            <select
              id="tutor-course-select"
              value={courseId}
              onChange={(e) => onSelectCourse(e.target.value)}
            >
              {courseOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  Khóa học: {c.topic}
                </option>
              ))}
            </select>
          </div>
        )}

        {globalSessions && globalSessions.total > 0 && (
          <details className="tutor-threads" style={{ marginBottom: 8 }}>
            <summary className="caption" style={{ cursor: "pointer", fontWeight: 600 }}>
              Phiên hỏi Sopi gần đây ({globalSessions.total})
            </summary>
            <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
              {globalSessions.thisWeek.length > 0 && (
                <div>
                  <div className="caption" style={{ fontWeight: 700, marginBottom: 4 }}>Tuần này</div>
                  <div style={{ display: "grid", gap: 4 }}>
                    {globalSessions.thisWeek.slice(0, 5).map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className="quick-chip"
                        style={{ textAlign: "left", justifyContent: "space-between", width: "100%" }}
                        onClick={() => {
                          if (s.courseId === courseId) {
                            void openThread(s.id);
                          } else {
                            onSelectSession?.(s.courseId, s.id);
                          }
                        }}
                      >
                        <span>{s.title || s.courseTopic}</span>
                        <span className="caption">{s.courseTopic}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {globalSessions.earlier.length > 0 && (
                <div>
                  <div className="caption" style={{ fontWeight: 700, marginBottom: 4 }}>Trước đó</div>
                  <div style={{ display: "grid", gap: 4 }}>
                    {globalSessions.earlier.slice(0, 5).map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className="quick-chip"
                        style={{ textAlign: "left", justifyContent: "space-between", width: "100%" }}
                        onClick={() => {
                          if (s.courseId === courseId) {
                            void openThread(s.id);
                          } else {
                            onSelectSession?.(s.courseId, s.id);
                          }
                        }}
                      >
                        <span>{s.title || s.courseTopic}</span>
                        <span className="caption">{s.courseTopic}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}

        {threads.data && threads.data.total > 0 && (
          <div className="tutor-threads" style={{ marginBottom: 8 }}>
            <label className="sr-only" htmlFor="tutor-thread-select">
              Chọn hội thoại
            </label>
            <select
              id="tutor-thread-select"
              value={threadId ?? ""}
              onChange={(e) => {
                const value = e.target.value;
                if (!value) {
                  setThreadId(null);
                  setMessages([]);
                  return;
                }
                void openThread(value);
              }}
            >
              <option value="">Hội thoại mới</option>
              {threads.data.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title || "Hội thoại"} ({item.messageCount} lượt)
                </option>
              ))}
            </select>
          </div>
        )}

        {notice && <p className="caption">{notice}</p>}

        <div className="tutor-scroll" ref={listRef} role="log" aria-live="polite" aria-relevant="additions text">
          {messages.length === 0 && (
            <p className="muted" style={{ fontSize: 13 }}>
              Hỏi Sopi về phần đang học — Sopi gợi mở từng bước và không đọc đáp án quiz.
            </p>
          )}

          {toolNotes.length > 0 && (
            <ul className="tutor-tool-notes" aria-label="Công cụ trợ giảng đã dùng">
              {toolNotes.map((note, index) => (
                <li key={`${note.name}-${index}`} className="tool-status-item">
                  <span
                    className={`tool-status-dot ${note.status === "ok" ? "is-ok" : "is-failed"}`}
                    aria-hidden="true"
                  >
                    <Icon name={note.status === "ok" ? "check" : "close"} size={12} />
                  </span>
                  <Badge tone={note.status === "ok" ? "muted" : "danger"}>
                    {TOOL_LABELS[note.name] ?? note.name}
                  </Badge>
                  <span>
                    {note.summary || (note.status === "ok" ? `Đã dùng ${note.name}` : `Không thể dùng ${note.name}`)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {messages.map((message) => (
            <div key={message.id} className={`tutor-message tutor-message-${message.role}`}>
              {message.role === "user" ? (
                <div className="bubble-user">{message.content}</div>
              ) : (
                <div className="bubble-assistant">
                  {message.content}
                  {message.status === "streaming" && (
                    <span className="tutor-caret" aria-hidden="true">
                      ▍
                    </span>
                  )}
                  {message.status === "failed" && (
                    <p className="error-text" style={{ marginTop: 6 }}>
                      Không hoàn tất
                      {message.errorCode
                        ? ` — ${STATUS_NOTE[message.errorCode] ?? message.errorCode}`
                        : ""}
                    </p>
                  )}
                  {message.status === "cancelled" && (
                    <p className="caption" style={{ marginTop: 6 }}>
                      Đã dừng — nội dung một phần được giữ lại.
                    </p>
                  )}
                </div>
              )}

              {message.role === "assistant" && message.citations && message.citations.length > 0 && (
                <div className="tutor-citations" aria-label="Trích dẫn đã xác minh vị trí">
                  <p className="caption" style={{ margin: 0 }}>
                    Nguồn đã xác minh vị trí:
                  </p>
                  <ul>
                    {message.citations.map((citation) => (
                      <li key={citation.chunkId}>
                        <a href={`/sources#${citation.sourceId}`} rel="noreferrer">
                          {citationLabel(citation)}
                        </a>
                        {citation.sectionAnchor ? ` · ${citation.sectionAnchor}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {message.role === "assistant" &&
                message.insufficientEvidence &&
                message.unverified &&
                message.unverified.length > 0 && (
                  <div className="tutor-citations tutor-citations-unverified">
                    <p className="caption" style={{ margin: 0 }}>
                      Chưa trích dẫn nguồn. Đoạn liên quan đã tìm thấy nhưng chưa được dẫn:
                    </p>
                    <ul>
                      {message.unverified.map((pointer) => (
                        <li key={pointer.chunkId}>
                          {pointer.sourceTitle ?? "Tài liệu"}
                          {pointer.pageNumber ? ` — tr.${pointer.pageNumber}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

              {message.role === "assistant" &&
                message.insufficientEvidence &&
                (!message.unverified || message.unverified.length === 0) &&
                message.status === "completed" && (
                  <p className="caption">Chưa đủ thông tin từ tài liệu để trả lời có căn cứ.</p>
                )}
            </div>
          ))}
          {actions.map((act) => (
            <ChangeCard
              key={act.actionId || act.id}
              courseId={courseId}
              initialAction={act}
              onReady={() => {
                queryClient.invalidateQueries({ queryKey: ["session"] });
              }}
            />
          ))}
        </div>

        {error && <div className="error-box" role="alert">{error}</div>}

        <div className="tutor-chips-row" aria-label="Gợi ý câu hỏi nhanh">
          {(PROMPT_CHIPS_BY_ENTRY[entryPoint] ?? PROMPT_CHIPS_BY_ENTRY.tab).map((chip) => (
            <button
              key={chip}
              type="button"
              className="tutor-chip"
              disabled={streaming || quotaExhausted}
              onClick={() => void send(chip)}
            >
              {chip}
            </button>
          ))}
        </div>

        <div className="tutor-composer">
          <label htmlFor="tutor-input" className="sr-only">
            Câu hỏi cho Sopi
          </label>
          <textarea
            id="tutor-input"
            value={text}
            maxLength={2000}
            placeholder="Hỏi Sopi về phần này…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                void send();
              }
            }}
            disabled={streaming || quotaExhausted}
          />
          {streaming ? (
            <Button variant="secondary" size="md" onClick={() => void stop()} disabled={stopping}>
              {stopping ? "Đang dừng" : "Dừng"}
            </Button>
          ) : (
            <Button
              className="tutor-send"
              aria-label="Gửi"
              onClick={() => void send()}
              disabled={quotaExhausted || text.trim().length === 0}
            >
              <Icon name="arrowRight" size={18} />
            </Button>
          )}
        </div>

        {quotaExhausted && (
          <p className="caption" style={{ marginTop: 8 }}>
            Bạn đã dùng hết hạn mức trợ giảng trong 24 giờ. Hạn mức sẽ tự làm mới.
          </p>
        )}
      </div>
    </>
  );
}
