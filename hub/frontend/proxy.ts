import { clerkMiddleware } from "@clerk/nextjs/server";
import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { isClerkEnabled } from "@/lib/auth/providers";

export function proxy(request: NextRequest, event: NextFetchEvent) {
  if (!isClerkEnabled()) {
    return NextResponse.next();
  }
  return clerkMiddleware()(request, event);
}

export const config = {
  matcher: ["/(api|trpc)(.*)", "/__clerk/:path*", "/((?!.*\\..*|_next).*)", "/"],
};
