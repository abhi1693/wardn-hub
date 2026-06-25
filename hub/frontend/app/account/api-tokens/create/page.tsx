"use client";

import Link from "next/link";
import { KeyRound, RefreshCw } from "lucide-react";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createApiToken } from "@/lib/api/hub";
import {
  APITokenScope,
  defaultScopes,
  expiryToIso,
  readOnlyScopes,
  ScopeCheckbox,
  scopeOptions,
  TOKEN_CREATED_STORAGE_KEY,
} from "../shared";

export default function CreateApiTokenPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [scopes, setScopes] = useState<APITokenScope[]>(defaultScopes);

  function setScope(scope: APITokenScope, enabled: boolean) {
    setScopes((current) => {
      if (enabled) return [...new Set([...current, scope])];
      return current.filter((value) => value !== scope);
    });
  }

  async function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || scopes.length === 0) return;
    setCreating(true);
    setError("");
    try {
      const response = await createApiToken({
        description: description.trim(),
        expires_at: expiryToIso(expiresOn),
        name: name.trim(),
        scopes,
      });
      window.sessionStorage.setItem(TOKEN_CREATED_STORAGE_KEY, response.token);
      router.push("/account/api-tokens");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create API token.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <PublicHeader />
      <main
        className="min-h-[calc(100dvh-64px)] bg-[#f6f8fb] py-8"
        style={{
          paddingInline:
            "max(var(--content-gutter), calc((100vw - var(--content-max-width)) / 2 + var(--content-gutter)))",
        }}
      >
        <div className="grid gap-5">
          <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid gap-1">
              <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <KeyRound className="size-6 text-muted-foreground" />
                <span>Create API token</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Choose only the scopes this token needs.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/account/api-tokens">All tokens</Link>
            </Button>
          </header>

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {error}
            </div>
          ) : null}

          <form
            className="overflow-hidden rounded-lg border border-border bg-white shadow-[var(--shadow-card)]"
            onSubmit={(event) => void submitToken(event)}
          >
            <section className="grid gap-6 p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-center gap-2">
                  <span className="inline-flex size-10 items-center justify-center rounded-md bg-slate-100 text-slate-700">
                    <KeyRound className="size-5" />
                  </span>
                  <div className="grid gap-1">
                    <h2 className="text-lg font-bold text-foreground">Token setup</h2>
                    <p className="text-sm text-muted-foreground">Name it, set an expiry, and choose access.</p>
                  </div>
                </div>
                <span className="inline-flex min-h-8 items-center rounded-full border border-slate-200 bg-slate-50 px-3 text-xs font-bold text-slate-700">
                  {scopes.length} selected
                </span>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="grid gap-2 lg:col-span-2">
                  <Label htmlFor="token-name">Name</Label>
                  <Input
                    id="token-name"
                    maxLength={100}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="CI publish token"
                    required
                    value={name}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="token-expiry">Expires on</Label>
                  <Input
                    id="token-expiry"
                    onChange={(event) => setExpiresOn(event.target.value)}
                    type="date"
                    value={expiresOn}
                  />
                </div>
                <div className="grid gap-2 lg:col-span-3">
                  <Label htmlFor="token-description">Description</Label>
                  <Input
                    id="token-description"
                    maxLength={200}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Used by release automation"
                    value={description}
                  />
                </div>
              </div>

              <div className="grid gap-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="font-bold text-foreground">Permissions</h3>
                    <p className="text-sm text-muted-foreground">Use a preset or select individual scopes.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      onClick={() => setScopes(readOnlyScopes)}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Read only
                    </Button>
                    <Button onClick={() => setScopes(defaultScopes)} size="sm" type="button" variant="outline">
                      Submission
                    </Button>
                    <Button
                      onClick={() => setScopes(scopeOptions.map((scope) => scope.value))}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Full access
                    </Button>
                  </div>
                </div>
                <div className="grid gap-1 rounded-lg border border-border p-2 md:grid-cols-2 xl:grid-cols-3">
                  {scopeOptions.map((scope) => (
                    <ScopeCheckbox
                      checked={scopes.includes(scope.value)}
                      description={scope.description}
                      key={scope.value}
                      label={scope.label}
                      onChange={(enabled) => setScope(scope.value, enabled)}
                    />
                  ))}
                </div>
              </div>
            </section>

            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-slate-50 px-5 py-4">
              <Button asChild type="button" variant="outline">
                <Link href="/account/api-tokens">Cancel</Link>
              </Button>
              <Button disabled={creating || !name.trim() || scopes.length === 0} type="submit">
                {creating ? <RefreshCw className="size-4" /> : <KeyRound className="size-4" />}
                {creating ? "Creating" : "Create token"}
              </Button>
            </div>
          </form>
        </div>
      </main>
    </>
  );
}
