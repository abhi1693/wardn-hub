"use client";

import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HubApiError, login, registerUser, setApiToken } from "@/lib/api/hub";

type AuthMode = "login" | "register";

function AuthPanelContent({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isRegister = mode === "register";
  const next = searchParams.get("next");
  const nextPath =
    next === "submit"
      ? "/submit"
      : next === "submissions"
        ? "/submissions"
        : next
          ? `/?section=${encodeURIComponent(next)}`
          : "/";
  const nextQuery = next ? `?next=${encodeURIComponent(next)}` : "";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");

    try {
      setApiToken("");
      if (isRegister) {
        const confirmPassword = String(formData.get("confirmPassword") ?? "");
        if (password !== confirmPassword) {
          setError("Passwords do not match.");
          setIsSubmitting(false);
          return;
        }

        await registerUser({
          email,
          password,
          first_name: String(formData.get("firstName") ?? ""),
          last_name: String(formData.get("lastName") ?? ""),
        });
      } else {
        await login({ email, password });
      }
    } catch (caught) {
      setIsSubmitting(false);
      if (caught instanceof HubApiError && caught.status === 409) {
        setError("An account already exists for that email.");
      } else if (caught instanceof HubApiError && caught.status === 401) {
        setError("The email or password is incorrect.");
      } else {
        setError(isRegister ? "Registration is currently unavailable." : "Sign in is currently unavailable.");
      }
      return;
    }

    router.replace(nextPath);
    router.refresh();
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-5">
      <Card className="w-full max-w-[420px]">
        <CardHeader className="space-y-6">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
              W
            </div>
            <div className="text-sm font-semibold">Wardn Hub</div>
          </div>
          <div>
            <CardTitle className="text-2xl">{isRegister ? "Create account" : "Sign in"}</CardTitle>
            <CardDescription>
              {isRegister ? "Create access to the MCP registry." : "Access your MCP registry workspace."}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" method="post" onSubmit={(event) => void handleSubmit(event)}>
            {isRegister ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="firstName">First name</Label>
                  <Input autoComplete="given-name" id="firstName" name="firstName" placeholder="First" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="lastName">Last name</Label>
                  <Input autoComplete="family-name" id="lastName" name="lastName" placeholder="Last" />
                </div>
              </div>
            ) : null}

            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                autoComplete="email"
                id="email"
                name="email"
                placeholder="admin@example.com"
                required
                type="email"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                autoComplete={isRegister ? "new-password" : "current-password"}
                id="password"
                minLength={isRegister ? 8 : undefined}
                name="password"
                placeholder="Enter password"
                required
                type="password"
              />
            </div>

            {isRegister ? (
              <div className="grid gap-2">
                <Label htmlFor="confirmPassword">Confirm password</Label>
                <Input
                  autoComplete="new-password"
                  id="confirmPassword"
                  minLength={8}
                  name="confirmPassword"
                  placeholder="Confirm password"
                  required
                  type="password"
                />
              </div>
            ) : null}

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <Button className="w-full" disabled={isSubmitting} type="submit">
              {isSubmitting
                ? isRegister
                  ? "Creating account"
                  : "Signing in"
                : isRegister
                  ? "Create account"
                  : "Sign in"}
            </Button>

            <p className="text-center text-sm text-muted-foreground">
              {isRegister ? "Already have an account?" : "Need an account?"}{" "}
              <Link
                className="font-medium text-primary underline-offset-4 hover:underline"
                href={isRegister ? `/login${nextQuery}` : `/register${nextQuery}`}
              >
                {isRegister ? "Sign in" : "Create account"}
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export function AuthPanel({ mode }: { mode: AuthMode }) {
  return (
    <Suspense fallback={<main className="flex min-h-dvh items-center justify-center bg-background p-5" />}>
      <AuthPanelContent mode={mode} />
    </Suspense>
  );
}
