"use client";

import { ClerkProvider } from "@clerk/nextjs";
import type { ReactNode } from "react";

import { clerkPublishableKey, isClerkEnabled } from "@/lib/auth/providers";

export function AuthProvider({ children }: { children: ReactNode }) {
  const publishableKey = clerkPublishableKey();

  if (!isClerkEnabled()) {
    return <>{children}</>;
  }

  return (
    <ClerkProvider publishableKey={publishableKey}>{children}</ClerkProvider>
  );
}
