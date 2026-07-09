"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { createOrganization, currentUser, updatePartnerOrganization } from "@/lib/api/hub";
import type { PartnerOrganizationUpdate } from "@/lib/api/generated/model";
import { protectedStateFromError, type ProtectedLoadState } from "@/lib/protected-route";

type PartnerStatus = NonNullable<PartnerOrganizationUpdate["partnerStatus"]>;
type PartnerTier = NonNullable<PartnerOrganizationUpdate["partnerTier"]>;
type PartnerSupportLevel = NonNullable<PartnerOrganizationUpdate["partnerSupportLevel"]>;
type AccessState = Exclude<ProtectedLoadState, "ready"> | "allowed";

function slugFromName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function canManagePartners(user: { is_superuser: boolean; is_global_partner_manager: boolean }) {
  return user.is_superuser || user.is_global_partner_manager;
}

export default function CreatePartnerPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [partnerStatus, setPartnerStatus] = useState<PartnerStatus>("active");
  const [partnerTier, setPartnerTier] = useState<PartnerTier>("verified");
  const [partnerSupportLevel, setPartnerSupportLevel] = useState<PartnerSupportLevel>("compatible");
  const [iconUrl, setIconUrl] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [supportEmail, setSupportEmail] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [accessState, setAccessState] = useState<AccessState>("loading");

  useEffect(() => {
    currentUser()
      .then((user) => {
        if (!canManagePartners(user)) {
          setError("Partner management requires partner manager access.");
          setAccessState("denied");
          return;
        }
        setAccessState("allowed");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Authentication required.");
        setAccessState(protectedStateFromError(caught));
      });
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const normalizedSlug = slugFromName(slug || name);
      const organization = await createOrganization({
        name: name.trim(),
        slug: normalizedSlug,
        iconUrl: iconUrl.trim(),
      });
      await updatePartnerOrganization(organization.id, {
        isPartner: true,
        partnerStatus,
        partnerTier,
        partnerSupportLevel,
        iconUrl: iconUrl.trim() || null,
        websiteUrl: websiteUrl.trim() || null,
        supportEmail: supportEmail.trim() || null,
        partnerInternalNotes: internalNotes.trim() || null,
      });
      router.push(`/partners/${organization.id}/edit`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create partner.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        {accessState === "loading" ? <ProtectedRouteState status="loading" /> : null}
        {accessState === "auth" ? <ProtectedRouteState status="auth" /> : null}
        {accessState === "denied" ? <ProtectedRouteState detail={error} status="denied" /> : null}
        {accessState === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

        {accessState === "allowed" ? (
        <>
        <section className="category-page-header">
          <div>
            <h1>Create Partner</h1>
            <p>Create an organization and mark it as a partner.</p>
          </div>
          <Link className="site-action-link" href="/partners">
            Partners
          </Link>
        </section>

        <form className="partner-form" onSubmit={(event) => void handleSubmit(event)}>
          {error ? <div className="error-banner">{error}</div> : null}

          <div className="partner-form-grid">
            <label>
              <span>Name</span>
              <input
                onChange={(event) => {
                  const nextName = event.target.value;
                  setName(nextName);
                  if (!slugEdited) setSlug(slugFromName(nextName));
                }}
                required
                value={name}
              />
            </label>
            <label>
              <span>Slug</span>
              <input
                onChange={(event) => {
                  const nextSlug = slugFromName(event.target.value);
                  setSlugEdited(Boolean(nextSlug));
                  setSlug(nextSlug);
                }}
                required
                value={slug}
              />
            </label>
            <label>
              <span>Partner Status</span>
              <select
                onChange={(event) => setPartnerStatus(event.target.value as PartnerStatus)}
                value={partnerStatus}
              >
                <option value="pending">pending</option>
                <option value="active">active</option>
                <option value="suspended">suspended</option>
                <option value="ended">ended</option>
              </select>
            </label>
            <label>
              <span>Partner Tier</span>
              <select
                onChange={(event) => setPartnerTier(event.target.value as PartnerTier)}
                value={partnerTier}
              >
                <option value="official">official</option>
                <option value="supported">supported</option>
                <option value="verified">verified</option>
                <option value="community">community</option>
              </select>
            </label>
            <label>
              <span>Support Level</span>
              <select
                onChange={(event) => setPartnerSupportLevel(event.target.value as PartnerSupportLevel)}
                value={partnerSupportLevel}
              >
                <option value="official">official</option>
                <option value="verified">verified</option>
                <option value="compatible">compatible</option>
                <option value="deprecated">deprecated</option>
              </select>
            </label>
            <label>
              <span>Icon URL</span>
              <input
                onChange={(event) => setIconUrl(event.target.value)}
                placeholder="https://example.com/icon.svg"
                type="url"
                value={iconUrl}
              />
            </label>
            <label>
              <span>Website URL</span>
              <input
                onChange={(event) => setWebsiteUrl(event.target.value)}
                type="url"
                value={websiteUrl}
              />
            </label>
            <label>
              <span>Support Email</span>
              <input
                onChange={(event) => setSupportEmail(event.target.value)}
                type="email"
                value={supportEmail}
              />
            </label>
          </div>

          {iconUrl.trim() ? (
            <div className="partner-icon-preview">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt="" src={iconUrl.trim()} />
              <span>{iconUrl.trim()}</span>
            </div>
          ) : null}

          <label>
            <span>Internal Notes</span>
            <textarea
              onChange={(event) => setInternalNotes(event.target.value)}
              rows={5}
              value={internalNotes}
            />
          </label>

          <div className="partner-form-actions">
            <Link className="site-action-link" href="/partners">
              Cancel
            </Link>
            <button className="site-nav-cta" disabled={isSubmitting} type="submit">
              {isSubmitting ? "Creating" : "Create Partner"}
            </button>
          </div>
        </form>
        </>
        ) : null}
      </main>
    </div>
  );
}
