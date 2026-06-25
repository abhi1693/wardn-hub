"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

type HeaderItem = {
  active?: boolean;
  href?: string;
  label: string;
  onClick?: () => void;
};

type SiteHeaderProps = {
  actions?: ReactNode;
  brandHref?: string;
  brandOnClick?: () => void;
  items?: HeaderItem[];
};

const publicItems: HeaderItem[] = [
  { href: "/", label: "Explore" },
  { href: "/categories", label: "Categories" },
  { href: "/users", label: "Users" },
  { href: "/submissions", label: "Submissions" },
];

function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function HeaderBrand({ href, onClick }: { href: string; onClick?: () => void }) {
  if (onClick) {
    return (
      <button className="site-brand" onClick={onClick} type="button">
        Wardn Hub
      </button>
    );
  }

  return (
    <Link className="site-brand" href={href}>
      Wardn Hub
    </Link>
  );
}

export function SiteHeader({ actions, brandHref = "/", brandOnClick, items }: SiteHeaderProps) {
  const pathname = usePathname();
  const navItems = items ?? publicItems;

  return (
    <header className="site-header">
      <HeaderBrand href={brandHref} onClick={brandOnClick} />
      <nav className="site-nav" aria-label="Primary">
        {navItems.map((item) => {
          const active = item.active ?? (item.href ? isActivePath(pathname, item.href) : false);
          const className = `site-nav-item ${active ? "active" : ""}`;

          if (item.href) {
            return (
              <Link className={className} href={item.href} key={`${item.label}-${item.href}`}>
                <span>{item.label}</span>
              </Link>
            );
          }

          return (
            <button
              className={className}
              key={item.label}
              onClick={item.onClick}
              type="button"
            >
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      {actions ? <div className="site-actions">{actions}</div> : null}
    </header>
  );
}

export function PublicHeader() {
  return (
    <SiteHeader
      actions={
        <Link className="site-nav-cta" href="/submit">
          List Server
        </Link>
      }
    />
  );
}
