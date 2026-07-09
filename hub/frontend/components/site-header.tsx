"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BellRing,
  Building2,
  ChevronDown,
  FileCheck2,
  KeyRound,
  LogIn,
  LogOut,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import {
  clerkTokenOptions,
  currentUser,
  currentUserWithToken,
  logout,
  setApiToken,
  signOutExternalAuth,
} from "@/lib/api/hub";
import type { UserRead } from "@/lib/api/generated/model";
import { isClerkEnabled } from "@/lib/auth/providers";

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
  { href: "/skills", label: "Skills" },
  { href: "/categories", label: "Categories" },
  { href: "/docs/api", label: "API docs" },
  { href: "/advertise", label: "Advertise" },
];

function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href.startsWith("/?")) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function canAccessAudit(user: UserRead | null) {
  return Boolean(user?.is_superuser);
}

function canManagePartners(user: UserRead | null) {
  return Boolean(user?.is_superuser || user?.is_global_partner_manager);
}

function BrandMark() {
  return (
    <svg
      aria-hidden="true"
      className="site-brand-mark"
      focusable="false"
      viewBox="0 0 40 40"
    >
      <rect className="site-brand-mark-bg" height="36" rx="10" width="36" x="2" y="2" />
      <path
        className="site-brand-mark-line"
        d="M12 15.5 20 10.8 28 15.5v9l-8 4.7-8-4.7v-9Z"
      />
      <path className="site-brand-mark-line" d="M20 10.8v7.8M12 15.5l8 4.7 8-4.7" />
      <circle className="site-brand-mark-node" cx="12" cy="15.5" r="2.45" />
      <circle className="site-brand-mark-node" cx="20" cy="10.8" r="2.45" />
      <circle className="site-brand-mark-node" cx="28" cy="15.5" r="2.45" />
      <path className="site-brand-mark-check" d="m16.2 23 2.55 2.55 5.25-6.1" />
    </svg>
  );
}

function HeaderBrand({ href, onClick }: { href: string; onClick?: () => void }) {
  const content = (
    <>
      <BrandMark />
      <span className="site-brand-text">Wardn Hub</span>
    </>
  );

  if (onClick) {
    return (
      <button className="site-brand" onClick={onClick} type="button">
        {content}
      </button>
    );
  }

  return (
    <Link className="site-brand" href={href}>
      {content}
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
            {canManagePartners(user) ? (
              <Link
                className="site-user-menu-item"
                href="/partners"
                onClick={() => setOpen(false)}
                role="menuitem"
              >
                <Building2 size={18} />
                <span>Partners</span>
              </Link>
            ) : null}
            {canAccessAudit(user) ? (
              <Link
                className="site-user-menu-item"
                href="/audit"
                onClick={() => setOpen(false)}
                role="menuitem"
              >
                <ShieldCheck size={18} />
                <span>Audit</span>
              </Link>
            ) : null}
            <Link
              className="site-user-menu-item"
              href="/account/api-tokens"
              onClick={() => setOpen(false)}
              role="menuitem"
            >
              <KeyRound size={18} />
              <span>API tokens</span>
            </Link>
            <Link
              className="site-user-menu-item"
              href="/account/events"
              onClick={() => setOpen(false)}
              role="menuitem"
            >
              <BellRing size={18} />
              <span>Events</span>
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

function PublicHeaderContent({
  externalSignedIn = false,
  loaded,
  onLogout,
  user,
}: {
  externalSignedIn?: boolean;
  loaded: boolean;
  onLogout: () => Promise<void>;
  user: UserRead | null;
}) {
  const isAuthenticated = Boolean(user);

  return (
    <SiteHeader
      items={publicItems}
      actions={
        isAuthenticated ? (
          <HeaderUserMenu onLogout={onLogout} user={user} />
        ) : externalSignedIn && loaded ? (
          <>
            <span className="site-auth-status">Signed in</span>
            <button className="site-action-link" onClick={() => void onLogout()} type="button">
              <LogOut size={16} />
              Sign out
            </button>
          </>
        ) : !loaded ? (
          <span className="site-auth-placeholder" aria-hidden="true" />
        ) : loaded ? (
          <Link className="site-nav-cta" href="/login">
            <LogIn size={15} />
            Sign in
          </Link>
        ) : null
      }
    />
  );
}

function LocalPublicHeader() {
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
    await signOutExternalAuth();
    setApiToken("");
    setUser(null);
    router.refresh();
  }

  return <PublicHeaderContent loaded={loaded} onLogout={handleLogout} user={user} />;
}

function ClerkPublicHeader() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn, signOut } = useAuth();
  const [user, setUser] = useState<UserRead | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let active = true;

    if (!isLoaded || !isSignedIn) {
      return () => {
        active = false;
      };
    }

    getToken(clerkTokenOptions())
      .then((token) => {
        if (!token) throw new Error("missing Clerk session token");
        return currentUserWithToken(token);
      })
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
  }, [getToken, isLoaded, isSignedIn]);

  async function handleLogout() {
    setSigningOut(true);
    setLoaded(false);
    try {
      await logout();
    } catch {
      // Keep the client state authoritative even if the session is already gone server-side.
    }
    setApiToken("");
    setUser(null);
    if (isSignedIn) {
      await signOut({ redirectUrl: "/" });
      return;
    }
    await signOutExternalAuth({ redirectUrl: "/" });
    router.refresh();
  }

  return (
    <PublicHeaderContent
      externalSignedIn={Boolean(isSignedIn && !signingOut)}
      loaded={!signingOut && isLoaded && (!isSignedIn || loaded)}
      onLogout={handleLogout}
      user={isSignedIn && !signingOut ? user : null}
    />
  );
}

export function PublicHeader() {
  if (isClerkEnabled()) {
    return <ClerkPublicHeader />;
  }

  return <LocalPublicHeader />;
}
