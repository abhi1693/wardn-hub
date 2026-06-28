import Link from "next/link";

import { PageLoader } from "@/components/page-loader";

export type ProtectedRouteStatus = "loading" | "auth" | "denied" | "error";

const defaultText: Record<ProtectedRouteStatus, { detail: string; title: string }> = {
  auth: {
    detail: "Sign in to continue.",
    title: "Sign in required",
  },
  denied: {
    detail: "Your account does not have access to this page.",
    title: "Access denied",
  },
  error: {
    detail: "Unable to load this page.",
    title: "Page unavailable",
  },
  loading: {
    detail: "Checking your access.",
    title: "Checking access",
  },
};

export function ProtectedRouteState({
  detail,
  signInHref = "/login",
  status,
  title,
}: {
  detail?: string;
  signInHref?: string;
  status: ProtectedRouteStatus;
  title?: string;
}) {
  const text = defaultText[status];

  if (status === "loading") {
    return <PageLoader label={title ?? text.title} />;
  }

  return (
    <div className="empty-state">
      <div className="empty-title">{title ?? text.title}</div>
      <div className="empty-detail">{detail || text.detail}</div>
      {status === "auth" ? (
        <div className="empty-actions">
          <Link className="site-action-link" href={signInHref}>
            Sign in
          </Link>
        </div>
      ) : null}
    </div>
  );
}
