"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon, { type IconName } from "../ui/Icon";
import { useSopi } from "./SopiContext";

type TabItem =
  | { kind: "link"; href: string; label: string; icon: IconName; match: (p: string) => boolean }
  | { kind: "sopi"; label: string; icon: IconName };

const TABS: TabItem[] = [
  { kind: "link", href: "/", label: "Trang chủ", icon: "home", match: (p) => p === "/" },
  { kind: "link", href: "/new", label: "Mới", icon: "plus", match: (p) => p.startsWith("/new") },
  { kind: "link", href: "/review", label: "Ôn tập", icon: "sparkle", match: (p) => p.startsWith("/review") },
  { kind: "sopi", label: "Sopi", icon: "chat" },
  {
    kind: "link",
    href: "/profile",
    label: "Hồ sơ",
    icon: "person",
    match: (p) => p.startsWith("/profile") || p.startsWith("/settings") || p.startsWith("/sources"),
  },
];

export default function TabBar() {
  const pathname = usePathname() ?? "/";
  const { open: sopiOpen, openSopi } = useSopi();

  return (
    <div className="tabbar">
      <div className="tabbar-inner">
        {TABS.map((tab) => {
          if (tab.kind === "sopi") {
            return (
              <button
                key="sopi"
                type="button"
                className={`tab-cell${sopiOpen ? " is-active" : ""}`}
                aria-expanded={sopiOpen}
                onClick={() => openSopi()}
              >
                <span className="tab-glyph" aria-hidden="true">
                  <Icon name={tab.icon} size={20} />
                </span>
                <span>{tab.label}</span>
              </button>
            );
          }
          const active = !sopiOpen && tab.match(pathname);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`tab-cell${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span className="tab-glyph" aria-hidden="true">
                <Icon name={tab.icon} size={20} />
              </span>
              <span>{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
