"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { translate, type I18nKey, type SupportedLanguage } from "./dictionaries";

const APP_LANG_KEY = "sopiskill:appLanguage";
const LESSON_LANG_KEY = "sopiskill:lessonLanguage";

interface I18nContextValue {
  appLanguage: SupportedLanguage;
  lessonLanguage: SupportedLanguage;
  setAppLanguage: (lang: SupportedLanguage) => void;
  setLessonLanguage: (lang: SupportedLanguage) => void;
  t: (key: I18nKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue>({
  appLanguage: "vi",
  lessonLanguage: "vi",
  setAppLanguage: () => {},
  setLessonLanguage: () => {},
  t: (key, vars) => translate("vi", key, vars),
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [appLanguage, setAppLanguageState] = useState<SupportedLanguage>("vi");
  const [lessonLanguage, setLessonLanguageState] = useState<SupportedLanguage>("vi");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedApp = window.localStorage.getItem(APP_LANG_KEY) as SupportedLanguage | null;
    const savedLesson = window.localStorage.getItem(LESSON_LANG_KEY) as SupportedLanguage | null;
    if (savedApp) setAppLanguageState(savedApp);
    if (savedLesson) setLessonLanguageState(savedLesson);
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = appLanguage;
    }
  }, [appLanguage]);

  const setAppLanguage = useCallback((lang: SupportedLanguage) => {
    setAppLanguageState(lang);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(APP_LANG_KEY, lang);
    }
  }, []);

  const setLessonLanguage = useCallback((lang: SupportedLanguage) => {
    setLessonLanguageState(lang);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LESSON_LANG_KEY, lang);
    }
  }, []);

  const t = useCallback(
    (key: I18nKey, vars?: Record<string, string | number>) => translate(appLanguage, key, vars),
    [appLanguage],
  );

  const value = useMemo(
    () => ({ appLanguage, lessonLanguage, setAppLanguage, setLessonLanguage, t }),
    [appLanguage, lessonLanguage, setAppLanguage, setLessonLanguage, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
