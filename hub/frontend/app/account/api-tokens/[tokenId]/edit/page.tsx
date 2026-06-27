"use client";

import Link from "next/link";
import { AlertCircle, KeyRound, RefreshCw, Save } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { HubApiError, listApiTokens, updateApiToken } from "@/lib/api/hub";
import type { UserAPITokenRead } from "@/lib/api/generated/model";
import {
  APITokenScope,
  ApiTokenForm,
  expiryToIso,
  isoToDateInput,
  LoadState,
  StatePanel,
} from "../../shared";

export default function EditApiTokenPage() {
  const params = useParams<{ tokenId: string }>();
  const router = useRouter();
  const tokenId = params.tokenId;
  const [state, setState] = useState<LoadState>("loading");
  const [token, setToken] = useState<UserAPITokenRead | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [scopes, setScopes] = useState<APITokenScope[]>([]);

  useEffect(() => {
    let active = true;
    listApiTokens()
      .then((response) => {
        if (!active) return;
        const record = response.tokens.find((item) => item.id === tokenId) ?? null;
        if (!record) {
          setState("error");
          setError("API token not found.");
          return;
        }
        setToken(record);
        setName(record.name);
        setDescription(record.description);
        setExpiresOn(isoToDateInput(record.expires_at));
        setIsActive(record.is_active);
        setScopes(record.scopes);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load API token.");
        setState(caught instanceof HubApiError && caught.status === 401 ? "auth" : "error");
      });
    return () => {
      active = false;
    };
  }, [tokenId]);

  async function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !name.trim() || scopes.length === 0) return;
    setSaving(true);
    setError("");
    try {
      await updateApiToken(token.id, {
        description: description.trim(),
        expires_at: expiryToIso(expiresOn),
        is_active: isActive,
        name: name.trim(),
        scopes,
      });
      router.push("/account/api-tokens");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update API token.");
    } finally {
      setSaving(false);
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
          {state === "ready" && token ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <KeyRound className="size-6 text-muted-foreground" />
                  <span>Edit API token</span>
                </h1>
                <p className="text-sm leading-6 text-muted-foreground">
                  Update token metadata, scopes, expiry, or active state.
                </p>
              </div>
              <Button asChild variant="outline">
                <Link href="/account/api-tokens">All tokens</Link>
              </Button>
            </header>
          ) : null}

          {state === "loading" ? (
            <ProtectedRouteState status="loading" />
          ) : null}
          {state === "auth" ? (
            <ProtectedRouteState status="auth" />
          ) : null}
          {state === "error" ? (
            <StatePanel
              detail={error || "Unable to load API token."}
              icon={AlertCircle}
              title="Unable to load token"
              tone="danger"
            />
          ) : null}
          {state === "ready" && token ? (
            <>
              {error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  {error}
                </div>
              ) : null}
              <ApiTokenForm
                description={description}
                expiresOn={expiresOn}
                isActive={isActive}
                name={name}
                onActiveChange={setIsActive}
                onDescriptionChange={setDescription}
                onExpiresOnChange={setExpiresOn}
                onNameChange={setName}
                onScopesChange={setScopes}
                onSubmit={(event) => void submitToken(event)}
                scopes={scopes}
                setupDetail={token.token_prefix}
                setupIcon={<Save className="size-5" />}
                submitIcon={<Save className="size-4" />}
                submitLabel="Save changes"
                submitting={saving}
                submittingIcon={<RefreshCw className="size-4" />}
                submittingLabel="Saving"
              />
            </>
          ) : null}
        </div>
      </main>
    </>
  );
}
