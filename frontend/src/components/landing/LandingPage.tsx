"use client";

import Link from "next/link";
import { useState } from "react";
import { ButtonLink, IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { useTheme } from "@/components/layout/ThemeProvider";

type SampleTopic = {
  chip: string;
  prompt: string;
  title: string;
  unitOne: string;
  nextLesson: string;
  nextMeta: string;
  lockedOne: string;
  lockedOneMeta: string;
  unitTwo: string;
  lockedTwo: string;
  lockedTwoMeta: string;
};

const SAMPLE_TOPICS: SampleTopic[] = [
  {
    chip: "Cách giấc ngủ hoạt động",
    prompt: "Tôi muốn hiểu cách giấc ngủ hoạt động",
    title: "Cách giấc ngủ hoạt động",
    unitOne: "Chương 1 · 0/2 bài",
    nextLesson: "Vì sao bạn buồn ngủ",
    nextMeta: "Bài tiếp theo · 2 phút",
    lockedOne: "Áp lực ngủ và nhịp sinh học",
    lockedOneMeta: "Đã khóa · 3 câu hỏi",
    unitTwo: "Chương 2 · đã khóa",
    lockedTwo: "Điều gì xảy ra vào ban đêm",
    lockedTwoMeta: "Đã khóa · 2 phút",
  },
  {
    chip: "Hợp âm hoạt động thế nào",
    prompt: "Tôi muốn hiểu hợp âm hoạt động thế nào",
    title: "Hợp âm hoạt động thế nào",
    unitOne: "Chương 1 · 0/2 bài",
    nextLesson: "Quãng và cao độ",
    nextMeta: "Bài tiếp theo · 3 phút",
    lockedOne: "Bộ ba trưởng và bộ ba thứ",
    lockedOneMeta: "Đã khóa · 3 câu hỏi",
    unitTwo: "Chương 2 · đã khóa",
    lockedTwo: "Vòng hợp âm phổ biến",
    lockedTwoMeta: "Đã khóa · 2 phút",
  },
  {
    chip: "Phơi sáng trong nhiếp ảnh",
    prompt: "Tôi muốn hiểu phơi sáng trong nhiếp ảnh",
    title: "Phơi sáng trong nhiếp ảnh",
    unitOne: "Chương 1 · 0/2 bài",
    nextLesson: "Tam giác phơi sáng",
    nextMeta: "Bài tiếp theo · 2 phút",
    lockedOne: "Khẩu độ và độ sâu trường ảnh",
    lockedOneMeta: "Đã khóa · 3 câu hỏi",
    unitTwo: "Chương 2 · đã khóa",
    lockedTwo: "Tốc độ màn trập",
    lockedTwoMeta: "Đã khóa · 2 phút",
  },
  {
    chip: "Vì sao La Mã sụp đổ",
    prompt: "Tôi muốn hiểu vì sao La Mã sụp đổ",
    title: "Vì sao La Mã sụp đổ",
    unitOne: "Chương 1 · 0/2 bài",
    nextLesson: "Nền cộng hòa muộn",
    nextMeta: "Bài tiếp theo · 3 phút",
    lockedOne: "Khủng hoảng thế kỷ thứ ba",
    lockedOneMeta: "Đã khóa · 3 câu hỏi",
    unitTwo: "Chương 2 · đã khóa",
    lockedTwo: "Dấu mốc cuối cùng",
    lockedTwoMeta: "Đã khóa · 2 phút",
  },
  {
    chip: "Thương lượng lương",
    prompt: "Tôi muốn học cách thương lượng lương",
    title: "Thương lượng lương",
    unitOne: "Chương 1 · 0/2 bài",
    nextLesson: "Hiểu giá trị thị trường của bạn",
    nextMeta: "Bài tiếp theo · 2 phút",
    lockedOne: "Khung đàm phán bốn bước",
    lockedOneMeta: "Đã khóa · 3 câu hỏi",
    unitTwo: "Chương 2 · đã khóa",
    lockedTwo: "Câu hỏi khó và cách đáp",
    lockedTwoMeta: "Đã khóa · 2 phút",
  },
];

const COMPARE_ROWS: { label: string; us: string; video: string; self: string }[] = [
  { label: "Lộ trình dựng riêng theo mục tiêu bạn nêu", us: "Có", video: "Không", self: "Không" },
  { label: "Bài học ngắn kèm quiz chấm phía máy chủ", us: "Có", video: "Một phần", self: "Không" },
  { label: "Hỏi trợ giảng dựa trên chính tài liệu của bạn", us: "Có, kèm trích dẫn", video: "Không", self: "Không" },
  { label: "Nhắc ôn tập khi kiến thức đến hạn", us: "Có", video: "Không", self: "Tự quản lý" },
  { label: "Đưa PDF hoặc trang web vào làm nguồn", us: "Có", video: "Không", self: "Không" },
];

const STEPS: { title: string; text: string }[] = [
  {
    title: "Nói mục tiêu của bạn",
    text: "Nhập một chủ đề, trả lời vài câu phỏng vấn ngắn để hệ thống biết bạn đã nắm gì và muốn đạt tới đâu.",
  },
  {
    title: "Duyệt lộ trình rồi bắt tay học",
    text: "Xem dàn bài đề xuất, chỉnh nếu cần, rồi để hệ thống soạn bài giảng ngắn cùng quiz. Điểm được chấm và lưu ở máy chủ.",
  },
  {
    title: "Điều chỉnh bất cứ lúc nào",
    text: "Đánh dấu bài đã xong, xem lại phần đến hạn ôn, và hỏi trợ giảng dựa trên tài liệu bạn đã tải lên.",
  },
];

/* Illustrative fragments only: they reuse SopiSkill's own classes and the same
   shapes the real screens use, so nothing here claims state the API returns. */
function StepArt({ index }: { index: number }) {
  if (index === 0) {
    return (
      <div className="landing-art" aria-hidden="true">
        <div className="landing-art-bubble">
          <span className="landing-art-label">Mục tiêu</span>
          <span className="landing-art-bubble-text">Tôi muốn hiểu cách giấc ngủ hoạt động</span>
        </div>
        <div className="landing-art-card">
          <span className="landing-art-label">Câu hỏi 1/5</span>
          <span className="landing-art-question">Bạn đã từng tìm hiểu về giấc ngủ chưa?</span>
          <div className="landing-art-options">
            <span className="landing-art-option is-picked">
              <b>A</b> Mới bắt đầu
            </span>
            <span className="landing-art-option">
              <b>B</b> Đã đọc vài bài
            </span>
          </div>
        </div>
      </div>
    );
  }
  if (index === 1) {
    return (
      <div className="landing-art" aria-hidden="true">
        <div className="landing-art-card">
          <span className="landing-art-label">Đề xuất · 2 chương</span>
          <span className="landing-art-question">Cách giấc ngủ hoạt động</span>
          <div className="landing-art-rows">
            <span className="landing-art-row">
              <b>01</b> Vì sao bạn buồn ngủ <em>2 phút</em>
            </span>
            <span className="landing-art-row">
              <b>02</b> Áp lực ngủ và nhịp sinh học <em>3 câu hỏi</em>
            </span>
          </div>
        </div>
        <div className="landing-art-card is-quiz">
          <span className="landing-art-label">Kiểm tra</span>
          <span className="landing-art-question">Adenosine tích lại khi nào?</span>
          <span className="landing-art-option is-picked">
            <b>A</b> Trong lúc thức
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="landing-art" aria-hidden="true">
      <div className="landing-art-card">
        <span className="landing-art-label">Đến hạn ôn hôm nay</span>
        <div className="landing-art-rows">
          <span className="landing-art-row">
            <b>Ôn</b> Chu kỳ giấc ngủ <em>3 thẻ</em>
          </span>
          <span className="landing-art-row">
            <b>Ôn</b> Nhịp sinh học <em>2 thẻ</em>
          </span>
        </div>
      </div>
      <div className="landing-art-bubble is-assistant">
        <span className="landing-art-label">Trợ giảng</span>
        <span className="landing-art-bubble-text">
          Theo tài liệu bạn tải lên, giấc ngủ sâu chiếm khoảng 15–25% tổng thời gian ngủ.
        </span>
        <span className="landing-art-cite">trang 4 · giac-ngu.pdf</span>
      </div>
    </div>
  );
}

function ThemeIconButton() {
  const { preference, toggle } = useTheme();
  const isDark = preference === "dark";
  return (
    <IconButton
      className="landing-theme-btn"
      onClick={toggle}
      aria-label={isDark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
    >
      <Icon name={isDark ? "sun" : "moon"} size={16} />
    </IconButton>
  );
}

function CoursePreview({ topic }: { topic: SampleTopic }) {
  return (
    <div className="landing-phone" aria-hidden="true">
      <div className="landing-phone-screen">
        <div className="landing-phone-status">
          <span>9:41</span>
          <span className="landing-phone-status-marks">▮▮▮</span>
        </div>

        <div className="landing-phone-body">
          <div className="landing-phone-toprow">
            <h3 className="landing-phone-title">{topic.title}</h3>
            <span className="landing-phone-count">
              <b>0</b>/4
            </span>
          </div>

          <div className="landing-phone-progress">
            <span style={{ width: "0%" }} />
          </div>
          <span className="landing-phone-progress-label">0/4 bài</span>

          <div className="landing-phone-unit">
            <span className="landing-phone-eyebrow">{topic.unitOne}</span>
            <span className="landing-phone-unit-title">Buổi tối</span>
          </div>

          <div className="landing-phone-next">
            <span className="landing-phone-next-eyebrow">{topic.nextMeta}</span>
            <span className="landing-phone-next-title">{topic.nextLesson}</span>
            <span className="landing-phone-start">Bắt đầu bài</span>
          </div>

          <div className="landing-phone-locked">
            <span className="landing-phone-locked-title">{topic.lockedOne}</span>
            <span className="landing-phone-locked-meta">{topic.lockedOneMeta}</span>
          </div>

          <div className="landing-phone-unit is-spaced">
            <span className="landing-phone-eyebrow is-locked">{topic.unitTwo}</span>
            <span className="landing-phone-unit-title">Qua đêm</span>
          </div>

          <div className="landing-phone-locked">
            <span className="landing-phone-locked-title">{topic.lockedTwo}</span>
            <span className="landing-phone-locked-meta">{topic.lockedTwoMeta}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const [selected, setSelected] = useState(0);
  const topic = SAMPLE_TOPICS[selected];

  return (
    <div className="landing">
      <header className="landing-header">
        <div className="landing-wrap landing-header-inner">
          <Link href="/" className="landing-brand">
            <span className="landing-brand-mark" aria-hidden="true">
              S
            </span>
            SopiSkill
          </Link>

          <nav className="landing-nav" aria-label="Giới thiệu">
            <a href="#how">Cách hoạt động</a>
            <a href="#compare">So sánh</a>
            <a href="#start">Bắt đầu</a>
          </nav>

          <div className="landing-header-actions">
            <ThemeIconButton />
            <ButtonLink href="/login" variant="dark" size="sm">
              Mở ứng dụng
            </ButtonLink>
          </div>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-wrap landing-hero-grid">
            <div className="landing-hero-copy">
              <span className="eyebrow">Học theo lộ trình</span>
              <h1 className="landing-h1">
                Học bất cứ điều gì.
                <br />
                <span className="landing-accent">Theo cách của bạn.</span>
              </h1>
              <p className="landing-sub">
                Nói cho SopiSkill biết bạn tò mò điều gì. Hệ thống phỏng vấn nhanh, dựng
                lộ trình bài học ngắn kèm quiz — rồi bạn quay lại học tiếp bất cứ lúc nào.
              </p>

              <div className="landing-cta-row">
                <ButtonLink href="/login" variant="dark" size="lg">
                  Tạo khóa học đầu tiên
                </ButtonLink>
                <span className="landing-cta-note">
                  Chưa cần gì ngoài một chủ đề bạn tò mò.
                </span>
              </div>

              <div className="landing-sample">
                <span className="landing-sample-label">
                  Thử một khóa mẫu. Không cần đăng ký.
                </span>
                <div className="landing-prompt" aria-live="polite">
                  {topic.prompt}
                </div>
                <div className="landing-chips" role="group" aria-label="Chọn chủ đề mẫu">
                  {SAMPLE_TOPICS.map((item, index) => (
                    <button
                      key={item.chip}
                      type="button"
                      className={`landing-chip${index === selected ? " is-active" : ""}`}
                      aria-pressed={index === selected}
                      onClick={() => setSelected(index)}
                    >
                      {item.chip}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="landing-phone-col">
              <CoursePreview topic={topic} />
            </div>
          </div>
        </section>

        <section id="how" className="landing-section">
          <div className="landing-wrap">
            <div className="landing-section-head">
              <h2 className="landing-section-title">Cách hoạt động</h2>
              <p className="landing-section-lede">
                Ba bước, không có video dài, không có danh sách link bỏ ngỏ.
              </p>
            </div>

            <ol className="landing-steps">
              {STEPS.map((step, index) => (
                <li key={step.title} className="landing-step">
                  <div className="landing-step-body">
                    <h3 className="landing-step-title">{step.title}</h3>
                    <p className="landing-step-text">{step.text}</p>
                  </div>
                  <span className="landing-step-num" aria-hidden="true">
                    {index + 1}
                  </span>
                  <div className="landing-step-art">
                    <StepArt index={index} />
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="compare" className="landing-section">
          <div className="landing-wrap">
            <div className="landing-section-head">
              <h2 className="landing-section-title">So sánh</h2>
              <p className="landing-section-lede">
                Đặt cạnh một khóa video thông thường và cách tự gom tài liệu để đọc.
              </p>
            </div>

            <div className="landing-table-wrap">
              <table className="landing-table">
                <thead>
                  <tr>
                    <th scope="col" className="landing-table-corner">
                      <span className="sr-only">Tiêu chí</span>
                    </th>
                    <th scope="col" className="is-us">
                      SopiSkill
                    </th>
                    <th scope="col">Khóa video</th>
                    <th scope="col">Tự đọc tài liệu</th>
                  </tr>
                </thead>
                <tbody>
                  {COMPARE_ROWS.map((row) => (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      <td className="is-us">{row.us}</td>
                      <td>{row.video}</td>
                      <td>{row.self}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="landing-table-note">
              So sánh dựa trên kiến trúc của SopiSkill: khóa học, quiz, nguồn tài liệu và
              ôn tập đều lấy dữ liệu từ máy chủ của chính bạn.
            </p>
          </div>
        </section>

        <section id="start" className="landing-cta">
          <div className="landing-wrap">
            <div className="landing-cta-card">
              <h2 className="landing-cta-title">Khóa học đầu tiên đang chờ bạn.</h2>
              <p className="landing-cta-text">
                Nhập một chủ đề. Hệ thống lo phần phỏng vấn, dàn bài và bài giảng.
              </p>
              <ButtonLink href="/login" variant="light" size="lg">
                Bắt đầu ngay
              </ButtonLink>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-wrap landing-footer-inner">
          <span className="landing-footer-brand">SopiSkill</span>
          <nav className="landing-footer-nav" aria-label="Chân trang">
            <a href="#how">Cách hoạt động</a>
            <a href="#compare">So sánh</a>
            <Link href="/login">Đăng nhập</Link>
          </nav>
          <span className="landing-footer-copy">© 2026 SopiSkill</span>
        </div>
      </footer>
    </div>
  );
}
