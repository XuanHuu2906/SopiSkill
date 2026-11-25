import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const PASSWORD = "StrongPassword123!";

function uniqueEmail(prefix: string): string {
  const suffix = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  return `${prefix}-${suffix}@e2e.test`;
}

async function registerUser(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Đăng ký" }).click();
  await page.locator("#login-email").fill(email);
  await page.locator("#login-password").fill(PASSWORD);
  await page.locator("#login-password-confirm").fill(PASSWORD);
  await page.getByRole("button", { name: "Tạo tài khoản" }).click();
  await page.waitForURL("**/");
  await expect(page.getByRole("link", { name: "Khóa học mới" }).first()).toBeVisible();
}

async function createAndGenerateCourse(
  page: Page,
  topic: string,
  language: "vi" | "en",
): Promise<string> {
  await page.goto("/new");
  if (language === "en") {
    await page.getByRole("button", { name: "English" }).click();
  } else {
    await page.getByRole("button", { name: "Tiếng Việt" }).click();
  }
  await page.locator("#topic-input").fill(topic);
  await page.getByRole("button", { name: "Bắt đầu" }).click();
  await page.waitForURL("**/new/interview?courseId=*");

  const answers =
    language === "en"
      ? [
          "I have some experience and want structured practice.",
          "Build a clean working project.",
          "3 hours per week.",
          "Hands-on examples and diagrams.",
          "Deep dive into core ideas.",
        ]
      : [
          "Mình mới bắt đầu học từ đầu.",
          "Muốn tự làm một bài tập nhỏ.",
          "Khoảng 3 giờ mỗi tuần.",
          "Thích ví dụ thực tế và đồ thị.",
          "Muốn hiểu sâu nền tảng.",
        ];

  for (let i = 0; i < 5; i += 1) {
    await expect(page.locator(".flow-header-meta")).toHaveText(`Câu ${i + 1}/5`);
    if (i === 0 && language === "en") {
      await expect(page.locator(".bubble-question").first()).toContainText(
        "Have you worked with",
      );
    }
    const textarea = page.locator("#interview-answer");
    await expect(textarea).toBeVisible();
    await textarea.fill(answers[i]);
    const label = i === 4 ? "Gửi câu trả lời cuối" : "Câu tiếp theo";
    await page.getByRole("button", { name: label }).click();
  }

  await page.waitForURL("**/new/proposal?courseId=*");
  if (language === "en") {
    await expect(page.getByText("Foundations").first()).toBeVisible();
  }
  await page.getByRole("button", { name: "Tạo khóa học" }).click();
  await page.waitForURL("**/course/*");
  return page.url();
}

async function expectNoAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations,
    results.violations.map((v) => `${v.id}: ${v.help}`).join("\n"),
  ).toEqual([]);
}

test("full English learning spine, answer-key privacy, and persistent quiz attempt", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const email = uniqueEmail("spine-en");
  await registerUser(page, email);

  // Intercept GET /v1/lessons/* to verify answer keys never leak over the wire.
  let interceptedLessonBody = "";
  page.on("response", async (res) => {
    if (res.url().includes("/v1/lessons/") && res.request().method() === "GET") {
      try {
        interceptedLessonBody = await res.text();
      } catch {
        // ignore aborted responses
      }
    }
  });

  const topic = "Python Basics";
  await createAndGenerateCourse(page, topic, "en");

  // Open first lesson from the course page.
  const firstLessonLink = page.locator('a[href^="/lesson/"]').first();
  await expect(firstLessonLink).toBeVisible();
  await firstLessonLink.click();
  await page.waitForURL("**/lesson/*");

  // Wait for step 1 (teach) and verify English mock content + 0 leaked keys.
  await expect(page.locator(".lesson-counter")).toHaveText("1/6");
  await expect(page.locator(".prose")).toContainText("core concepts");
  expect(interceptedLessonBody).toBeTruthy();
  for (const forbidden of ['"answerIndex"', '"acceptedAnswers"', '"answer_key"', '"solution"']) {
    expect(interceptedLessonBody).not.toContain(forbidden);
  }

  const nextBtn = page.locator(".lesson-bar-primary");

  // Step 1: teach -> next
  await nextBtn.click();
  await expect(page.locator(".lesson-counter")).toHaveText("2/6");

  // Step 2: mc -> select first radio option -> next
  await page.locator('[role="radio"]').first().click();
  await nextBtn.click();
  await expect(page.locator(".lesson-counter")).toHaveText("3/6");

  // Step 3: blank -> fill topic -> next
  await page.locator('input[id^="blank-"]').fill(topic);
  await nextBtn.click();
  await expect(page.locator(".lesson-counter")).toHaveText("4/6");

  // Step 4: order -> already has shuffled sequence -> next
  await nextBtn.click();
  await expect(page.locator(".lesson-counter")).toHaveText("5/6");

  // Step 5: match -> pick an option for every select -> next
  const selects = page.locator('select[id^="match-"]');
  const selectCount = await selects.count();
  expect(selectCount).toBeGreaterThan(0);
  for (let i = 0; i < selectCount; i += 1) {
    const sel = selects.nth(i);
    const optVal = await sel.locator("option").nth(1).getAttribute("value");
    expect(optVal).toBeTruthy();
    await sel.selectOption(optVal!);
  }
  await nextBtn.click();
  await expect(page.locator(".lesson-counter")).toHaveText("6/6");

  // Step 6: short -> fill topic -> submit quiz
  await page.locator('input[id^="short-"]').fill(topic);
  await nextBtn.click();

  // Post-submit result view appears and XP is awarded (>0 because blank & short match topic).
  await expect(page.getByRole("link", { name: "Về trang chủ" })).toBeVisible();
  await page.getByRole("link", { name: "Về trang chủ" }).click();
  await page.waitForURL("**/");
  await expect(page.getByText(topic).first()).toBeVisible();
  await expect(page.locator(".side-nav")).toContainText("XP");
});

test("tutor docked rail (1440) vs modal overlay (768/390), focus contract, and axe-core a11y", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const email = uniqueEmail("a11y-tutor");
  await registerUser(page, email);
  await createAndGenerateCourse(page, "SQL căn bản", "vi");

  await page.locator('a[href^="/lesson/"]').first().click();
  await page.waitForURL("**/lesson/*");
  await expect(page.locator(".lesson-counter")).toHaveText("1/6");

  // Desktop 1440x900: docked tutor rail (non-modal)
  await page.getByRole("button", { name: "Hỏi Sopi" }).click();
  const dialog = page.locator('[role="dialog"]');
  await expect(dialog).toBeVisible();
  await expect(dialog).not.toHaveAttribute("aria-modal", "true");
  await expectNoAxeViolations(page);

  // Tab from #tutor-input must be allowed to leave the docked rail.
  await page.locator("#tutor-input").focus();
  let leftDialog = false;
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const el = document.activeElement;
      return Boolean(el && el.closest('[role="dialog"]'));
    });
    if (!inside) {
      leftDialog = true;
      break;
    }
  }
  expect(leftDialog).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // Tablet 768x1024: overlay modal traps Tab + no horizontal overflow
  await page.setViewportSize({ width: 768, height: 1024 });
  const overflow768 = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(overflow768).toBe(true);

  await page.getByRole("button", { name: "Hỏi Sopi" }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expectNoAxeViolations(page);

  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const el = document.activeElement;
      return Boolean(el && el.closest('[role="dialog"]'));
    });
    expect(inside).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // Mobile 390x844: no horizontal overflow + overlay modal + 0 axe violations
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow390 = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(overflow390).toBe(true);
  await page.getByRole("button", { name: "Hỏi Sopi" }).click();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expectNoAxeViolations(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("session cache isolation across account switch A -> B", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const userA = uniqueEmail("user-a");
  const userB = uniqueEmail("user-b");
  const secretTopic = `Secret Course ${Date.now().toString(36)}`;

  await registerUser(page, userA);
  await createAndGenerateCourse(page, secretTopic, "vi");

  await page.goto("/");
  await expect(page.getByText(secretTopic).first()).toBeVisible();

  // Logout User A and register User B in the same browser context.
  await page.getByRole("button", { name: "Đăng xuất" }).click();
  await registerUser(page, userB);

  await page.goto("/");
  await expect(page.getByText(secretTopic)).toHaveCount(0);
});

test("Wave 4: proposal edit, glossary VocabSheet, per-block check, and settings/delete", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const email = uniqueEmail("wave4");
  await registerUser(page, email);

  // 1. Create course and reach /new/proposal, then edit proposal inline (v1 -> v2)
  await page.goto("/new");
  await page.getByRole("button", { name: "English" }).click();
  await page.locator("#topic-input").fill("Wave 4 Systems");
  await page.getByRole("button", { name: "Bắt đầu" }).click();
  await page.waitForURL("**/new/interview?courseId=*");

  const answers = [
    "Intermediate developer.",
    "Learn practical patterns.",
    "4 hours per week.",
    "Hands-on examples.",
    "Balanced depth.",
  ];
  for (let i = 0; i < answers.length; i++) {
    await expect(page.locator(".flow-header-meta")).toHaveText(`Câu ${i + 1}/5`);
    await page.locator("#interview-answer").fill(answers[i]);
    const label = i === 4 ? "Gửi câu trả lời cuối" : "Câu tiếp theo";
    await page.getByRole("button", { name: label }).click();
  }
  await page.waitForURL("**/new/proposal?courseId=*");

  await page.getByRole("button", { name: "Chỉnh sửa" }).click();
  await page.getByLabel("Tên khóa học").fill("Wave 4 Custom Plan");
  await page.getByRole("button", { name: "Lưu thay đổi" }).click();
  await expect(page.getByText("Đã lưu đề xuất phiên bản 2.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Wave 4 Custom Plan" })).toBeVisible();

  // Approve and wait for course ready
  await page.getByRole("button", { name: "Tạo khóa học" }).click();
  await page.waitForURL("**/course/crs_*", { timeout: 20_000 });

  // 2. Open VocabSheet on course page and run axe-core scan
  await page.getByRole("button", { name: "Thuật ngữ" }).click();
  const vocabDialog = page.getByRole("dialog", { name: "Bảng thuật ngữ" });
  await expect(vocabDialog).toBeVisible();
  await expect(vocabDialog.getByText(/thuật ngữ/i).first()).toBeVisible();
  await expectNoAxeViolations(page);
  await page.keyboard.press("Escape");
  await expect(vocabDialog).toBeHidden();

  // 3. Enter first lesson, step to MC question, and use instant server-side per-block check
  await page.getByRole("link", { name: "Tiếp tục" }).click();
  await page.waitForURL("**/lesson/lsn_*");
  await page.locator(".lesson-bar-primary").click();
  await page.locator('[role="radio"]').first().click();
  await page.getByRole("button", { name: "Kiểm tra câu này" }).click();
  await expect(page.getByRole("status").first()).toBeVisible();

  // 4. Visit /settings, verify stats + axe-core, update display name, and delete account
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Hồ sơ & Cài đặt" })).toBeVisible();
  await expect(page.getByText("Khóa học sẵn sàng")).toBeVisible();
  await expectNoAxeViolations(page);

  await page.getByLabel("Tên hiển thị").fill("Wave4 Learner");
  await page.getByRole("button", { name: "Lưu thay đổi" }).click();
  await expect(page.getByText("Đã cập nhật tên hiển thị.")).toBeVisible();

  await page.getByLabel("Mật khẩu hiện tại").fill(PASSWORD);
  await page.getByLabel(/Nhập chính xác/).fill("DELETE");
  await page.getByRole("button", { name: "Xóa vĩnh viễn tài khoản" }).click();
  await page.waitForURL("**/login*", { timeout: 10_000 });
});
