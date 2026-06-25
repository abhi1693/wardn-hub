import { clerkMiddleware } from "@clerk/nextjs/server";
import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";

function clientAuthProviders() {
  return (process.env.NEXT_PUBLIC_AUTH_PROVIDERS ?? "local")
    .split(",")
    .map((provider) => provider.trim().toLowerCase())
    .filter(Boolean);
}

function clerkEnabled() {
  return (
    clientAuthProviders().includes("clerk") &&
    Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)
  );
}

export function proxy(request: NextRequest, event: NextFetchEvent) {
  if (!clerkEnabled()) {
    return NextResponse.next();
  }
  return clerkMiddleware()(request, event);
}

export const config = {
  matcher: ["/(api|trpc)(.*)", "/__clerk/:path*", "/((?!.*\\..*|_next).*)", "/"],
};
