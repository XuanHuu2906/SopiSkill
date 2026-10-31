"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchTutorThread,
  fetchTutorThreads,
  newClientId,
  streamTutorMessage,
  TutorStreamError,
  type TutorStreamEvent,
  type TutorThread,
} from "@/lib/api";
import { useSessionQueryKey } from "../../providers";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "streaming" | "completed" | "failed" | "cancelled";
  errorCode?: string | null;
}

const STATUS_NOTE: Record<string, string> = {
  TUTOR_DISABLED: "Trợ giảng AI chưa được bật trên hệ thống này.",
  TUTOR_CONTEXT_INVALID: "Ngữ cảnh bài học không hợp lệ, hãy tải lại trang.",
  MESSAGE_IN_PROGRESS: "Câu hỏi trước đang được xử lý, hãy chờ hoặc tải lại lịch sử.",
  TUTOR_LIMIT_REACHED: "Bạn đã hết lượt hỏi trợ giảng trong 24 giờ qua.",
  TUTOR_TIMEOUT: "Hết thời gian chờ câu trả lời.",
};

export default function TutorPanel({
  courseId,
  lessonId,
  activeBlockIndex,
  blockLabel,
}: {
  courseId: string;
  lessonId: string;
  activeBlockIndex: number;
  blockLabel?: string;
}) {
  const queryClient = useQueryClient();
  const threadsKey = useSessionQueryKey("tutor-threads", courseId);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const messageIdRef = useRef<string | null>(null);

  const threads = useQuery({
    queryKey: threadsKey,
    queryFn: () => fetchTutorThreads(courseId),
    retry: false,
  });

  // Auto-scroll trong vùng chat (không scroll cả trang) — WCAG-friendly.
  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const openThread = useCallback(
    async (id: string) => {
      setError(null);
      try {
        const thread: TutorThread = await fetchTutorThread(courseId, id);
        setThreadId(thread.id);
        setNotice(thread.notice);
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
      const targetId = event.data.messageId ?? messageIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId ? { ...m, status: "completed" } : m
        )
      );
      return;
    }
    if (event.event === "error") {
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

  async function send() {
    const question = text.trim();
    if (!question || streaming) return;
    setError(null);
    const clientMessageId = newClientId("tmsg");
    messageIdRef.current = null;
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

    try {
      await streamTutorMessage(
        courseId,
        {
          clientMessageId,
          threadId,
          text: question,
          contextRef: { lessonId, blockIndex: activeBlockIndex },
        },
        {
          signal: controller.signal,
          onThreadId: (id) => setThreadId(id),
          onEvent: (event) => {
            if (event.data.messageId && !messageIdRef.current) {
              messageIdRef.current = event.data.messageId;
              // Map placeholder → messageId thật để delta tiếp theo cập nhật đúng.
              const realId = event.data.messageId;
              const previous = assistantId;
              assistantId = realId;
              setMessages((prev) =>
                prev.map((m) => (m.id === previous ? { ...m, id: realId } : m))
              );
            }
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
        }
      );
      queryClient.invalidateQueries({ queryKey: threadsKey });
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

  function stop() {
    abortRef.current?.abort();
  }

  return (
    <section className="card tutor-panel" aria-labelledby="tutor-heading">
      <div className="topbar" style={{ marginBottom: 8 }}>
        <h2 id="tutor-heading">Trợ giảng AI</h2>
        <span className="badge badge-muted">
          {blockLabel ? `Block #${activeBlockIndex} · ${blockLabel}` : `Block #${activeBlockIndex}`}
        </span>
      </div>
      <p className="muted">
        Trợ giảng trả lời dựa trên bài đang học và không đọc đáp án quiz. Câu trả lời có thể
        chưa được kiểm chứng với nguồn tài liệu.
      </p>

      {threads.data && threads.data.total > 0 && (
        <div className="tutor-threads">
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

      {notice && <p className="muted">{notice}</p>}

      <div
        className="tutor-messages"
        ref={listRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {messages.length === 0 && (
          <p className="muted">Chưa có câu hỏi nào trong bài này.</p>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`tutor-message tutor-message-${message.role}`}
          >
            <span className="badge badge-muted">
              {message.role === "user" ? "Bạn" : "Trợ giảng"}
            </span>
            <p>
              {message.content}
              {message.status === "streaming" && (
                <span className="tutor-caret" aria-hidden="true">
                  ▍
                </span>
              )}
            </p>
            {message.status === "failed" && (
              <p className="error-text">
                Không hoàn tất
                {message.errorCode
                  ? ` (${STATUS_NOTE[message.errorCode] ?? message.errorCode})`
                  : ""}
              </p>
            )}
            {message.status === "cancelled" && (
              <p className="muted">Đã dừng — nội dung một phần được giữ lại.</p>
            )}
          </div>
        ))}
      </div>

      {error && <div className="error-box">{error}</div>}

      <label htmlFor="tutor-input" className="sr-only">
        Câu hỏi cho trợ giảng
      </label>
      <textarea
        id="tutor-input"
        value={text}
        maxLength={2000}
        placeholder="Hỏi về block này… (Ctrl+Enter để gửi)"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            void send();
          }
        }}
        disabled={streaming}
      />
      <div className="tutor-actions">
        <button onClick={send} disabled={streaming || text.trim().length === 0}>
          {streaming ? "Đang trả lời…" : "Gửi câu hỏi"}
        </button>
        {streaming && (
          <button className="secondary" onClick={stop}>
            Dừng
          </button>
        )}
      </div>
    </section>
  );
}
