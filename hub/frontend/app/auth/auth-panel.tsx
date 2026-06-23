"use client";

import { ArrowLeft, Database, LockKeyhole, LogIn, Mail, User, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { HubApiError, login, registerUser, setApiToken } from "@/lib/api/hub";

type AuthMode = "login" | "register";

function AuthPanelContent({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const isRegister = mode === "register";
  const next = searchParams.get("next");
  const nextPath = next ? `/?section=${encodeURIComponent(next)}` : "/";
  const nextQuery = next ? `?next=${encodeURIComponent(next)}` : "";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (isRegister && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      setApiToken("");
      if (isRegister) {
        await registerUser({
          email,
          password,
          first_name: firstName,
          last_name: lastName,
        });
      } else {
        await login({ email, password });
      }
      router.push(nextPath);
      router.refresh();
    } catch (caught) {
      if (caught instanceof HubApiError && caught.status === 409) {
        setError("An account already exists for that email.");
      } else {
        setError(caught instanceof Error ? caught.message : "Authentication failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-layout" aria-labelledby="auth-title">
        <div className="auth-identity">
          <Link className="auth-back" href="/">
            <ArrowLeft size={16} />
            Back to registry
          </Link>
          <div className="auth-brand">
            <Database size={22} />
            <span>Wardn Hub</span>
          </div>
          <div>
            <p className="eyebrow">Access control</p>
            <h1 id="auth-title">{isRegister ? "Create your account" : "Sign in to Wardn Hub"}</h1>
            <p className="auth-copy">
              {isRegister
                ? "Use a work email to create a session for submissions, namespace claims, partner records, and audit access."
                : "Use your Wardn Hub account to manage submissions, namespace trust, partner support, and operational reviews."}
            </p>
          </div>
          <dl className="auth-proof">
            <div>
              <dt>Session security</dt>
              <dd>HTTP-only cookie</dd>
            </div>
            <div>
              <dt>Protected workflows</dt>
              <dd>Submissions, namespaces, partners</dd>
            </div>
            <div>
              <dt>Registry browsing</dt>
              <dd>Public access</dd>
            </div>
          </dl>
        </div>

        <form className="auth-card" onSubmit={(event) => void submit(event)}>
          <div className="auth-card-head">
            <div className="auth-card-icon">
              {isRegister ? <UserPlus size={19} /> : <LockKeyhole size={19} />}
            </div>
            <div>
              <h2>{isRegister ? "Register" : "Login"}</h2>
              <p>{isRegister ? "Start with a standard user account." : "Continue with your existing account."}</p>
            </div>
          </div>

          {isRegister && (
            <div className="auth-name-grid">
              <label className="auth-field">
                <span>First name</span>
                <span className="auth-input-wrap">
                  <User size={16} />
                  <input
                    autoComplete="given-name"
                    onChange={(event) => setFirstName(event.target.value)}
                    value={firstName}
                  />
                </span>
              </label>
              <label className="auth-field">
                <span>Last name</span>
                <span className="auth-input-wrap">
                  <User size={16} />
                  <input
                    autoComplete="family-name"
                    onChange={(event) => setLastName(event.target.value)}
                    value={lastName}
                  />
                </span>
              </label>
            </div>
          )}

          <label className="auth-field">
            <span>Email</span>
            <span className="auth-input-wrap">
              <Mail size={16} />
              <input
                autoComplete="email"
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </span>
          </label>

          <label className="auth-field">
            <span>Password</span>
            <span className="auth-input-wrap">
              <LockKeyhole size={16} />
              <input
                autoComplete={isRegister ? "new-password" : "current-password"}
                minLength={isRegister ? 8 : undefined}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </span>
          </label>

          {isRegister && (
            <label className="auth-field">
              <span>Confirm password</span>
              <span className="auth-input-wrap">
                <LockKeyhole size={16} />
                <input
                  autoComplete="new-password"
                  minLength={8}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                  type="password"
                  value={confirmPassword}
                />
              </span>
            </label>
          )}

          {error && <div className="error-banner">{error}</div>}

          <button className="auth-submit" disabled={loading} type="submit">
            {isRegister ? <UserPlus size={17} /> : <LogIn size={17} />}
            {loading ? "Working" : isRegister ? "Create account" : "Sign in"}
          </button>

          <p className="auth-switch">
            {isRegister ? "Already have an account?" : "Need an account?"}{" "}
            <Link href={isRegister ? `/login${nextQuery}` : `/register${nextQuery}`}>
              {isRegister ? "Sign in" : "Create account"}
            </Link>
          </p>
        </form>
      </section>
    </main>
  );
}

export function AuthPanel({ mode }: { mode: AuthMode }) {
  return (
    <Suspense fallback={<div className="auth-page" />}>
      <AuthPanelContent mode={mode} />
    </Suspense>
  );
}
