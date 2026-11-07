"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Traps Tab inside a modal panel, closes on Escape, and restores focus to the
 * element that opened it.
 *
 * `initialFocusSelector` picks where focus lands on open. `onClose` is held in a
 * ref because call sites pass an inline arrow; putting it in the deps would
 * re-run the trap on every parent render and pull focus back mid-typing.
 */
export default function useModalPanel({
  open,
  onClose,
  panelRef,
  initialFocusSelector,
  modal = true,
}: {
  open: boolean;
  onClose: () => void;
  panelRef: React.RefObject<HTMLElement | null>;
  initialFocusSelector?: string;
  /**
   * `false` for a docked panel: the page beside it stays reachable by keyboard
   * and screen reader, so there is no Tab trap and no inert sweep. Escape and
   * focus restoration still apply.
   */
  modal?: boolean;
}) {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;

    function focusables(): HTMLElement[] {
      if (!panel) return [];
      return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
    }

    const preferred = initialFocusSelector
      ? panel?.querySelector<HTMLElement>(initialFocusSelector)
      : null;
    (preferred ?? focusables()[0] ?? panel)?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel || !modal) return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !panel.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !panel.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    // `aria-modal` only tells assistive tech to ignore the background; the DOM
    // still exposes it. Mark every sibling along the panel's ancestor chain
    // inert so screen-reader and programmatic focus cannot leave the panel.
    // The backdrop stays live: it is the click-to-close target.
    const inerted: HTMLElement[] = [];
    if (modal) {
      let node: HTMLElement | null = panel;
      while (node && node !== document.body) {
        const parent: HTMLElement | null = node.parentElement;
        if (!parent) break;
        for (const sibling of Array.from(parent.children)) {
          const el = sibling as HTMLElement;
          if (el === node || el.classList.contains("tutor-backdrop") || el.hasAttribute("inert")) continue;
          el.setAttribute("inert", "");
          inerted.push(el);
        }
        node = parent;
      }
    }

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      for (const el of inerted) el.removeAttribute("inert");
      opener?.focus?.();
    };
  }, [open, panelRef, initialFocusSelector, modal]);
}
