"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { shadcn } from "@clerk/ui/themes";
import type { ReactNode } from "react";

function clientAuthProviders() {
  return (process.env.NEXT_PUBLIC_AUTH_PROVIDERS ?? "local")
    .split(",")
    .map((provider) => provider.trim().toLowerCase())
    .filter(Boolean);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const clerkEnabled = clientAuthProviders().includes("clerk");

  if (!clerkEnabled || !publishableKey) {
    return <>{children}</>;
  }

  return (
    <ClerkProvider appearance={{ theme: shadcn }} publishableKey={publishableKey}>
      {children}
    </ClerkProvider>
  );
}
