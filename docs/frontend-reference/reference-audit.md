# Reference audit — PolySkill web (observed 2026-11-03)

## Scope and method

| Item | Value |
|---|---|
| Reference product | `https://web.polyskill.app` (Expo SDK 57 / React Native Web bundle) |
| Tooling | REA 6.7.0 CLI (`list-browser-targets`, `inspect-web-page`, `capture-web-screenshot`) + a read-only CDP driver (`Runtime.evaluate`, `Page.captureScreenshot`, `Emulation.setDeviceMetricsOverride`) |
| Browser | Chrome 156.0.8078.76, loopback CDP `127.0.0.1:9222`, isolated profile |
| Bundle analysed statically | `/_expo/static/js/web/entry-a3803cab42a2ab75ae9ef2e391ee92d0.js`, 5 849 374 B, SHA-256 `e7f84aaffae7a3be5d943437e1ccd084a69c12aad1675f3bcc841703bde5d4ce` |
| Viewports captured | 1440x900, 768x1024, 390x844 (DPR 1) |
| Observed session | Signed-in account already open in the isolated profile; no credentials were read, typed, or stored |

Actions performed were limited to: navigation between routes the UI itself exposes,
opening the existing course, opening lesson 1, stepping through the lesson, answering
one multiple-choice question, and opening the tutor panel that already contained
history from a previous owner session. No data was created, edited or deleted during
this session.

## Evidence labels

- **FACT** — directly measured (computed style, bounding box, screenshot, bundle string).
- **INFERENCE** — consistent conclusion from several facts, not directly measured.
- **UNKNOWN** — not observable without acting on the account or reading the server.
- **PROPOSAL** — a SopiSkill design decision, not present in the reference.

## What the reference is built with (FACT)

- Expo Router file routes: `(tabs)/home`, `(tabs)/new`, `(tabs)/profile`, `(tabs)/course/[id]`,
  `lesson/[id]/index`, `lesson/[id]/complete`, `new/interview`, `new/generating`, `new/source`,
  `onboarding`, `sign-in`, `league/index`.
- TanStack Query with polling (`/generation` polled ~56 times during one generation).
- Design tokens are CSS custom properties injected at runtime
  (`--c-*` for colour, `--shadow-*` for elevation), theme switched by
  `data-theme` on `<html>` or `prefers-color-scheme`.
- Fonts: `Manrope_700Bold` / `Manrope_800ExtraBold` for display, `Inter_400/500/600`
  for body/labels, `JetBrainsMono` for code.
- Desktop is a hard breakpoint: `DESKTOP_MIN_WIDTH = 1024`; below it the tab bar
  moves to the bottom, at/above it a 264 px side navigation replaces it.

## Non-goals

- No PolySkill API was called except requests the page itself issued while navigating.
- No backend behaviour of PolySkill is inferred from UI; SopiSkill keeps its own
  FastAPI contracts (`docs/specs/05-API-CONTRACTS.md`).
- No PolySkill logo, mascot, illustration, copy string or font file is copied into
  SopiSkill. Palette/spacing/typography **scales** are reproduced because they are
  observable layout properties; brand marks and assets are SopiSkill's own.

## Ground truth for SopiSkill (unchanged by this work)

- Next.js 15.5.28 App Router, React 19, TanStack Query 5, TypeScript strict.
- Session-scoped query keys (`useSessionQueryKey`), HttpOnly cookie + CSRF header,
  generation polling that stops on terminal state, stable `clientAttemptId`,
  server-side grading and progress. All of that is preserved.
