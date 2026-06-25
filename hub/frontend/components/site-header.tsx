"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ChevronDown, FileCheck2, KeyRound, LogIn, LogOut, UserPlus } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

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

function getUserName(user: UserRead | null) {
  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
  return user?.display_name?.trim() || fullName || user?.email?.split("@")[0] || "Account";
}

function getUserDetail(user: UserRead | null, displayName: string) {
  if (!user?.email) return "";
  return user.email === displayName ? "" : user.email;
}

function getUserInitials(displayName: string) {
  const segments = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  const initials = segments.map((segment) => segment[0]?.toUpperCase() ?? "").join("");
  return initials || "WH";
}

export function HeaderUserMenu({
  onLogout,
  user,
}: {
  onLogout: () => Promise<void> | void;
  user: UserRead | null;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const displayName = getUserName(user);
  const detail = getUserDetail(user, displayName);
  const initials = getUserInitials(displayName);

  useEffect(() => {
    if (!open) return undefined;

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="site-user-menu" ref={menuRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="site-user-trigger"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="site-user-avatar" aria-hidden="true">
          {initials}
        </span>
        <ChevronDown className="site-user-chevron" size={15} />
      </button>
      {open ? (
        <div className="site-user-dropdown" role="menu">
          <div className="site-user-dropdown-header">
            <span className="site-user-dropdown-avatar" aria-hidden="true">
              {initials}
            </span>
            <span className="site-user-dropdown-identity">
              <strong>{displayName}</strong>
              {detail ? <small>{detail}</small> : null}
            </span>
          </div>

          <div className="site-user-dropdown-section">
            <span className="site-user-dropdown-label">Management</span>
            <Link
              className="site-user-menu-item"
              href="/submissions"
              onClick={() => setOpen(false)}
              role="menuitem"
            >
              <FileCheck2 size={18} />
              <span>My submissions</span>
            </Link>
            <Link
              className="site-user-menu-item"
              href="/account/api-tokens"
              onClick={() => setOpen(false)}
              role="menuitem"
            >
              <KeyRound size={18} />
              <span>API tokens</span>
            </Link>
          </div>

          <div className="site-user-menu-separator" />
          <button
            className="site-user-menu-item destructive"
            onClick={() => {
              setOpen(false);
              void onLogout();
            }}
            role="menuitem"
            type="button"
          >
            <LogOut size={18} />
            <span>Sign out</span>
          </button>
        </div>
      ) : null}
    </div>
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
          <HeaderUserMenu onLogout={handleLogout} user={user} />
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
