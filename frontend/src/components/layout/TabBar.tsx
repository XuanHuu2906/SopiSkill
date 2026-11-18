"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon, { type IconName } from "../ui/Icon";

const TABS: { href: string; label: string; icon: IconName; match: (p: string) => boolean }[] = [
  { href: "/", label: "Trang chủ", icon: "home", match: (p) => p === "/" },
  { href: "/new", label: "Mới", icon: "plus", match: (p) => p.startsWith("/new") },
  { href: "/sources", label: "Tài liệu", icon: "book", match: (p) => p.startsWith("/sources") },
  { href: "/review", label: "Ôn tập", icon: "sparkle", match: (p) => p.startsWith("/review") },
];

export default function TabBar() {
  const pathname = usePathname() ?? "/";
  return (
    <div className="tabbar">
      <div className="tabbar-inner">
        {TABS.map((tab) => {
          const active = tab.match(pathname);
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
