"use client";

import Link from "next/link";
import { KeyRound, RefreshCw } from "lucide-react";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { createApiToken } from "@/lib/api/hub";
import {
  ApiTokenForm,
  defaultScopes,
  expiryToIso,
  TOKEN_CREATED_STORAGE_KEY,
} from "../shared";

export default function CreateApiTokenPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [scopes, setScopes] = useState(defaultScopes);

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

          <ApiTokenForm
            description={description}
            descriptionPlaceholder="Used by release automation"
            expiresOn={expiresOn}
            name={name}
            namePlaceholder="CI publish token"
            onDescriptionChange={setDescription}
            onExpiresOnChange={setExpiresOn}
            onNameChange={setName}
            onScopesChange={setScopes}
            onSubmit={(event) => void submitToken(event)}
            scopes={scopes}
            setupDetail="Name it, set an expiry, and choose access."
            setupIcon={<KeyRound className="size-5" />}
            submitIcon={<KeyRound className="size-4" />}
            submitLabel="Create token"
            submitting={creating}
            submittingIcon={<RefreshCw className="size-4" />}
            submittingLabel="Creating"
          />
        </div>
      </main>
    </>
  );
}
