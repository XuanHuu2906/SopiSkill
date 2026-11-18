# Design tokens

All values are **FACT** unless marked otherwise. Colour names are SopiSkill's own; the
values were read from the reference's injected CSS custom properties and from computed
styles on live DOM nodes (see `evidence/dom-*.json` → `rootVars`).

## Colour — light

| Token | Value | Role in reference UI |
|---|---|---|
| `--ink` | `#241C3B` | Primary text, filled dark buttons, slab |
| `--ink2` | `#4F476B` | Body text |
| `--ink3` | `#8A82A6` | Meta text, captions, disabled labels — **SopiSkill ships `#645C81`** (see below) |
| `--cream` | `#FCFAFF` | Side nav surface, tab bar surface, button fg on dark |
| `--bone` | `#F2EDFE` | Chips, hover rows, secondary circles |
| `--linen` | `#E6DEFA` | Borders, progress tracks, option borders |
| `--sand` | `#CDC1EF` | Disabled fills |
| `--ember` | `#7B5BE6` | Primary accent, hero surface, selected border |
| `--ember-deep` | `#5A38C6` | Accent text, primary pressed, eyebrow |
| `--wash` | `#EBE3FF` | Active nav row, selected option fill, chips |
| `--wash-soft` | `#F7F3FF` | Stat strip background |
| `--moss` | `#2F9B86` | Success fill |
| `--moss-deep` | `#1F7A68` | Success text, success CTA |
| `--clay` | `#C4457E` | Wrong answer fill |
| `--clay-deep` | `#A8336A` | Wrong answer text |
| `--danger` | `#C43B4A` | Error text |
| `--danger-wash` | `#FBEDF0` | Error surface |
| `--surface` | `#FFFFFF` | Cards, assistant bubbles |
| `--wash-border` | `#D6C9F8` | Selected/outline borders |
| `--moss-wash` | `#E2F5F0` | Correct card surface |
| `--clay-wash` | `#FCEAF2` | Wrong card surface |
| `--paper` | `#F1ECFD` | App background |
| `--scrim` | `rgba(36,28,59,0.42)` | Overlay |

## Colour — dark (FACT, measured with forced `prefers-color-scheme: dark`)

| Token | Value |
|---|---|
| `--ink` | `#EFE9FC` |
| `--ink2` | `#B8AED6` |
| `--ink3` | `#8479A8` — **SopiSkill ships `#9F94C5`** (see below) |
| `--cream` | `#191430` |
| `--bone` | `#221B3C` |
| `--linen` | `#302748` |
| `--sand` | `#493C6E` |
| `--ember` | `#9B7BFF` |
| `--ember-deep` | `#C3ADFF` |
| `--wash` | `#2C2350` |
| `--wash-soft` | `#241D42` |
| `--moss` | `#4CC3A8` |
| `--moss-deep` | `#6FD6BE` |
| `--clay` | `#E77CAE` |
| `--clay-deep` | `#F29AC4` |
| `--danger` | `#F2788A` |
| `--danger-wash` | `#3A1E25` |
| `--surface` | `#1F1839` |
| `--wash-border` | `#453A6B` |
| `--moss-wash` | `#15332D` |
| `--clay-wash` | `#331E29` |
| `--paper` | `#120E20` |
| `--scrim` | `rgba(9,6,18,0.62)` |

## Deliberate deviations from the reference (IMPLEMENTED, 2026-11-03)

| Token | Reference (FACT) | SopiSkill (IMPLEMENTED) | Reason |
|---|---|---|---|
| `--ink3` light | `#8A82A6` | `#645C81` | Reference value measured 3.12–3.61:1 on `cream`/`bone`/`wash`/`paper`; below the 4.5:1 floor. New value ≥4.78:1 on every surface token. |
| `--ink3` dark | `#8479A8` | `#9F94C5` | Same defect; reference 4.09–4.46:1. New value ≥4.98:1. |
| `.hero-card` eyebrow/kicker/step | `opacity` 0.82 / 0.92 / 0.75 | no opacity, pure `--on-accent` | Compositing white at those opacities over `--ember #7B5BE6` yielded `#F4F2FD` (4.23:1) and `#DED6F9` (3.36:1). axe flagged both. |

These are the only token-level departures. Everything else in the tables above is shipped
verbatim. Verified by axe-core over 9 routes in both themes — 0 violations, 18 runs.

## Typography (FACT)

Families used by the reference: `Manrope_700Bold`, `Manrope_800ExtraBold`,
`Inter_400Regular`, `Inter_500Medium`, `Inter_600SemiBold`, `JetBrainsMono_400Regular`.

SopiSkill loads **Manrope** (700/800) and **Inter** (400/500/600) through `next/font`
so no self-hosted font file is added to the repo.

| Variant | Size / line | Weight | Tracking | Colour |
|---|---|---|---|---|
| displayXl | 48 / 52 | 800 | −0.032em | ink |
| hero | 40 / 44 | 800 | −0.03em | ink |
| largeTitle | 34 / 40 | 800 | −0.028em | ink |
| title1 | 28 / 34 | 800 | −0.024em | ink |
| title2 | 22 / 28 | 700 | −0.018em | ink |
| title3 | 19 / 24 | 700 | −0.012em | ink |
| headline | 17 / 22 | 600 | −0.013em | ink |
| body | 17 / 27 | 400 | −0.013em | ink2 |
| bodyLarge | 19 / 31 | 400 | −0.016em | ink2 |
| callout | 15 / 22 | 400 | −0.009em | ink2 |
| subhead | 15 / 20 | 500 | −0.009em | ink2 |
| footnote | 13 / 18 | 400 | −0.003em | ink3 |
| caption | 12 / 16 | 500 | 0 | ink3 |
| eyebrow | 13 / 18 | 600 | −0.003em | emberDeep |
| label | 15 / 20 | 600 | −0.009em | ink |
| labelLarge | 17 / 22 | 600 | −0.013em | ink |
| stat | 28 / 32 | 800 | −0.02em | ink |
| statSmall | 19 / 24 | 800 | −0.01em | ink |
| tab | 11 / 13 | 600 | +0.005em | ink3 |
| code | 14 / 20 | mono 400 | 0 | ink |

## Spacing (FACT)

`xxs 2, xs 4, sm 8, md 12, lg 16, xl 20, 2xl 24, 3xl 32, 4xl 40, 5xl 48, 6xl 64`

## Radius (FACT)

`xs 6, sm 10, md 16, lg 22, xl 28, pill 999`

## Layout (FACT)

| Token | Value |
|---|---|
| `screenPadding.horizontal` | 20 |
| `screenPadding.headerTop` | 8 |
| `screenPadding.bottom` | 24 |
| `screenPadding.desktopHorizontal` | 48 |
| `screenPadding.desktopTop` | 48 |
| `screenPadding.desktopBottom` | 72 |
| `contentWidth.page` | 1040 |
| `contentWidth.reading` | 720 |
| `contentWidth.form` | 680 |
| `contentWidth.narrow` | 560 |
| side nav width | 264 |
| desktop breakpoint | 1024 |
| mobile tab bar height | 50 (+ safe area) |
| hit slop | 8 on all sides |

## Elevation (FACT)

| Token | Light |
|---|---|
| `card` | `0 1px 2px rgba(74,45,150,.06), 0 8px 20px -10px rgba(74,45,150,.18)` |
| `raised` | `0 2px 6px rgba(74,45,150,.07), 0 20px 40px -18px rgba(74,45,150,.36)` |
| `overlay` | `0 28px 64px -20px rgba(21,14,43,.5)` |
| `sheet` | `0 -14px 44px -12px rgba(74,45,150,.3)` |
| `glow` | `0 14px 30px -12px rgba(123,91,230,.6)` |
| `knob` | `0 2px 5px -1px rgba(74,45,150,.45)` |
| `rail` | `-18px 0 48px -32px rgba(74,45,150,.4)` |

Dark shadows are documented in `evidence/dom-home-dark-1440x900.json` and are the same
geometry with black at higher opacity.

## Motion (FACT — bundle constant table)

| Token | ms |
|---|---|
| press | 120 |
| toggle | 180 |
| feedback | 200 |
| sheet | 280 |
| rise | 280 |
| pop | 320 |
| bar | 420 |
| draw | 900 |
| count | 900 |
| lift | 600 |
| shake | 360 |

Easing: `cubic-bezier(0.23, 1, 0.32, 1)` for appears/press-release,
`cubic-bezier(0.2, 0.7, 0.2, 1)` for tab transitions. Button press scales to 0.98.

## Button hierarchy (FACT)

| Variant | Fill | Foreground | Notes |
|---|---|---|---|
| primary | ember | `#FFFFFF` | 56 px tall (lg), padding-x 32 |
| dark | ink (`#241C3B`) | cream | OAuth primary |
| secondary | wash | emberDeep | `Hỏi Pol` |
| ghost/light | surface | ink / emberDeep | white pills on dark surfaces |
| success | moss | onEmber | answered correctly |
| wrong | clay | onEmber | answered wrong |
| disabled | sand | `rgba(16,16,16,·)` | measured on `Kiểm tra` |
| text | transparent | emberDeep | inline actions |

Sizes: `lg 56/32`, `md 48/24`, `sm 38/16`.

## Cards (FACT)

`default` white + `card` shadow; `tint` bone; `accent` wash; `hero` ember + `glow`;
`dark` slab; `dashed` 1.5 px dashed sand; `correct` moss-wash; `wrong` clay-wash.
Base radius 22, padded 20 (some hero cards measured with 32).

## Inputs (FACT)

Textarea composer 50 px tall, radius 22, 1 px linen border, 16 px horizontal padding,
17/27 text. Chat composer sends with a 48 px pill button.
