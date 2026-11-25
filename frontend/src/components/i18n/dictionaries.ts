export type SupportedLanguage =
  | "vi"
  | "en"
  | "ja"
  | "ko"
  | "zh"
  | "es"
  | "fr"
  | "de"
  | "pt"
  | "id"
  | "th"
  | "hi";

export const LANGUAGE_OPTIONS: { code: SupportedLanguage; label: string; nativeLabel: string }[] = [
  { code: "vi", label: "Vietnamese", nativeLabel: "Tiếng Việt" },
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "ja", label: "Japanese", nativeLabel: "日本語" },
  { code: "ko", label: "Korean", nativeLabel: "한국어" },
  { code: "zh", label: "Chinese", nativeLabel: "中文" },
  { code: "es", label: "Spanish", nativeLabel: "Español" },
  { code: "fr", label: "French", nativeLabel: "Français" },
  { code: "de", label: "German", nativeLabel: "Deutsch" },
  { code: "pt", label: "Portuguese", nativeLabel: "Português" },
  { code: "id", label: "Indonesian", nativeLabel: "Bahasa Indonesia" },
  { code: "th", label: "Thai", nativeLabel: "ไทย" },
  { code: "hi", label: "Hindi", nativeLabel: "हिन्दी" },
];

export const VI_DICT = {
  "nav.home": "Trang chủ",
  "nav.new": "Khóa học mới",
  "nav.sources": "Tài liệu",
  "nav.review": "Ôn tập",
  "nav.profile": "Hồ sơ",
  "nav.askSopi": "Hỏi Sopi",
  "nav.settings": "Cài đặt",
  "nav.logout": "Đăng xuất",
  "nav.lightMode": "Chế độ sáng",
  "nav.darkMode": "Chế độ tối",
  "nav.yourCourses": "Khóa học của bạn",
  "nav.notifications": "Thông báo",
  "settings.eyebrow": "Tài khoản",
  "settings.title": "Hồ sơ & Cài đặt",
  "settings.stats": "Thống kê học tập",
  "settings.profile": "Thông tin hiển thị",
  "settings.displayName": "Tên hiển thị",
  "settings.saveChanges": "Lưu thay đổi",
  "settings.saving": "Đang lưu…",
  "settings.saved": "Đã cập nhật tên hiển thị.",
  "settings.languageSection": "Ngôn ngữ (tách riêng giao diện & bài học)",
  "settings.appLanguage": "Ngôn ngữ giao diện ứng dụng",
  "settings.lessonLanguage": "Ngôn ngữ bài học mặc định",
  "settings.languageNote": "Đổi ngôn ngữ giao diện không làm thay đổi ngôn ngữ bài học mặc định của bạn.",
  "settings.languageSaved": "Đã lưu cài đặt ngôn ngữ.",
  "settings.avatarSection": "Ảnh đại diện",
  "settings.changeAvatar": "Đổi ảnh đại diện",
  "settings.appearance": "Giao diện",
  "settings.notifications": "Thông báo & Giờ yên lặng",
  "settings.reminderTime": "Giờ nhắc học hằng ngày (bước 15 phút)",
  "settings.quietHours": "Khung giờ yên lặng (22:00–08:00 mặc định)",
  "settings.dailyReminder": "Nhắc học hằng ngày",
  "settings.streakGuard": "Cảnh báo bảo vệ chuỗi",
  "settings.weeklyRecap": "Tổng kết tuần",
  "settings.comebackNudge": "Nhắc quay lại (ngày 2, 4, 8, 15)",
  "settings.webPush": "Thông báo đẩy trình duyệt (Web Push)",
  "settings.saveNotifications": "Lưu lịch thông báo",
  "settings.notificationsSaved": "Đã lưu tùy chọn thông báo.",
  "settings.identities": "Tài khoản liên kết & Bảo mật phiên",
  "settings.logoutAll": "Đăng xuất mọi thiết bị",
  "settings.dangerZone": "Khu vực nguy hiểm",
  "settings.deleteAccount": "Xóa tài khoản",
  "onboarding.eyebrow": "Cá nhân hóa",
  "onboarding.title": "Thiết lập lộ trình học của bạn",
  "onboarding.stepOf": "Bước {step}/4",
  "onboarding.next": "Tiếp tục",
  "onboarding.back": "Quay lại",
  "onboarding.finish": "Hoàn tất thiết lập",
  "onboarding.bannerTitle": "Cá nhân hóa trải nghiệm SopiSkill (4 bước)",
  "onboarding.bannerDesc": "Cho Sopi biết vai trò, chủ đề yêu thích và phong cách học để tạo khóa học sát nhu cầu hơn.",
  "onboarding.bannerCta": "Thiết lập ngay",
  "login.oauthDivider": "Hoặc tiếp tục với",
  "login.continueGoogle": "Tiếp tục với Google",
  "login.continueApple": "Tiếp tục với Apple",
  "notifications.title": "Trung tâm thông báo",
  "notifications.markAll": "Đọc tất cả",
  "notifications.empty": "Chưa có thông báo mới nào.",
} as const;

export type I18nKey = keyof typeof VI_DICT;

export const EN_DICT: Record<I18nKey, string> = {
  "nav.home": "Home",
  "nav.new": "New Course",
  "nav.sources": "Sources",
  "nav.review": "Review",
  "nav.profile": "Profile",
  "nav.askSopi": "Ask Sopi",
  "nav.settings": "Settings",
  "nav.logout": "Sign out",
  "nav.lightMode": "Light mode",
  "nav.darkMode": "Dark mode",
  "nav.yourCourses": "Your courses",
  "nav.notifications": "Notifications",
  "settings.eyebrow": "Account",
  "settings.title": "Profile & Settings",
  "settings.stats": "Learning stats",
  "settings.profile": "Display info",
  "settings.displayName": "Display name",
  "settings.saveChanges": "Save changes",
  "settings.saving": "Saving…",
  "settings.saved": "Display name updated.",
  "settings.languageSection": "Languages (App UI & Lesson Content)",
  "settings.appLanguage": "App interface language",
  "settings.lessonLanguage": "Default lesson language",
  "settings.languageNote": "Changing the app interface language keeps your default lesson language independent.",
  "settings.languageSaved": "Language preferences saved.",
  "settings.avatarSection": "Avatar",
  "settings.changeAvatar": "Change avatar",
  "settings.appearance": "Appearance",
  "settings.notifications": "Notifications & Quiet Hours",
  "settings.reminderTime": "Daily study reminder (15-min steps)",
  "settings.quietHours": "Quiet hours (22:00–08:00 default)",
  "settings.dailyReminder": "Daily study reminder",
  "settings.streakGuard": "Streak protection alert",
  "settings.weeklyRecap": "Weekly recap",
  "settings.comebackNudge": "Comeback nudges (days 2, 4, 8, 15)",
  "settings.webPush": "Browser Web Push notifications",
  "settings.saveNotifications": "Save notification schedule",
  "settings.notificationsSaved": "Notification preferences saved.",
  "settings.identities": "Linked accounts & Sessions",
  "settings.logoutAll": "Sign out all devices",
  "settings.dangerZone": "Danger zone",
  "settings.deleteAccount": "Delete account",
  "onboarding.eyebrow": "Personalize",
  "onboarding.title": "Set up your learning profile",
  "onboarding.stepOf": "Step {step}/4",
  "onboarding.next": "Continue",
  "onboarding.back": "Back",
  "onboarding.finish": "Finish setup",
  "onboarding.bannerTitle": "Personalize SopiSkill (4 quick steps)",
  "onboarding.bannerDesc": "Tell Sopi your role, interests, and preferred learning style for tailored courses.",
  "onboarding.bannerCta": "Start setup",
  "login.oauthDivider": "Or continue with",
  "login.continueGoogle": "Continue with Google",
  "login.continueApple": "Continue with Apple",
  "notifications.title": "Notification Center",
  "notifications.markAll": "Mark all read",
  "notifications.empty": "No notifications yet.",
};

export function translate(lang: SupportedLanguage, key: I18nKey, vars?: Record<string, string | number>): string {
  const dict = lang === "vi" ? VI_DICT : EN_DICT;
  let text: string = dict[key] ?? VI_DICT[key];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replace(`{${k}}`, String(v));
    }
  }
  return text;
}
