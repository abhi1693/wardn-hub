import Link from "next/link";
import { LoaderCircle } from "lucide-react";

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
    return (
      <div
        aria-label={title ?? text.title}
        className="grid min-h-[190px] place-items-center p-6"
        role="status"
      >
        <LoaderCircle aria-hidden="true" className="size-7 animate-spin text-muted-foreground" />
      </div>
    );
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
