"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FileCheck2, LogIn, Plus, UserPlus } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { currentUser, logout, setApiToken } from "@/lib/api/hub";
import type { UserRead } from "@/lib/api/generated/model";

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
];

const adminItems: HeaderItem[] = [
  { href: "/submissions", label: "Submissions" },
  { href: "/partners", label: "Partners" },
  { href: "/?section=audit", label: "Audit" },
];

function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href.startsWith("/?")) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function isAdminUser(user: UserRead | null) {
  return Boolean(
    user?.is_superuser || user?.is_global_moderator || user?.is_global_partner_manager,
  );
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
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    currentUser()
      .then((response) => {
        if (active) setUser(response);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoaded(true);
      });

    return () => {
      active = false;
    };
  }, []);

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // Keep the client state authoritative even if the session is already gone server-side.
    }
    setApiToken("");
    setUser(null);
    router.refresh();
  }

  const navItems = isAdminUser(user) ? [...publicItems, ...adminItems] : publicItems;
  const isAuthenticated = Boolean(user);

  return (
    <SiteHeader
      items={navItems}
      actions={
        isAuthenticated ? (
          <>
            <Link className="site-action-link" href="/submissions">
              <FileCheck2 size={16} />
              My submissions
            </Link>
            <Link className="site-nav-cta" href="/submit">
              <Plus size={16} />
              List Server
            </Link>
            <button className="site-action-link" onClick={() => void handleLogout()} type="button">
              Sign out
            </button>
          </>
        ) : loaded ? (
          <>
            <Link className="site-nav-cta" href="/login">
              <LogIn size={15} />
              Sign in
            </Link>
            <Link className="site-action-link" href="/register">
              <UserPlus size={16} />
              Create account
            </Link>
          </>
        ) : null
      }
    />
  );
}
