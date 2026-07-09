"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import {
  currentUser,
  listPartnerOrganizations,
  updatePartnerOrganization,
} from "@/lib/api/hub";
import type { PartnerOrganizationRead } from "@/lib/api/generated/model";
import { protectedStateFromError, type ProtectedLoadState } from "@/lib/protected-route";

type LoadState = ProtectedLoadState;

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function canManagePartners(user: { is_superuser: boolean; is_global_partner_manager: boolean }) {
  return user.is_superuser || user.is_global_partner_manager;
}

export default function PartnersPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [partners, setPartners] = useState<PartnerOrganizationRead[]>([]);
  const [deletingPartnerId, setDeletingPartnerId] = useState("");

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      currentUser()
        .then(async (user) => {
          if (!canManagePartners(user)) {
            setError("Partner management requires partner manager access.");
            setState("denied");
            return null;
          }
          return listPartnerOrganizations();
        })
        .then((response) => {
          if (!response) return;
          setPartners(response.organizations);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load partners.");
          setState(protectedStateFromError(caught));
        });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, []);

  async function deletePartner(partner: PartnerOrganizationRead) {
    const confirmed = window.confirm(
      `Remove ${partner.name} from partners? The organization record will remain.`,
    );
    if (!confirmed) return;

    setDeletingPartnerId(partner.id);
    setError("");
    try {
      await updatePartnerOrganization(partner.id, {
        isPartner: false,
        partnerStatus: "none",
      });
      setPartners((current) => current.filter((item) => item.id !== partner.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete partner.");
    } finally {
      setDeletingPartnerId("");
    }
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
        {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
        {state === "denied" ? <ProtectedRouteState detail={error} status="denied" /> : null}
        {state === "error" ? (
          <ProtectedRouteState detail={error} status="error" title="Partners unavailable" />
        ) : null}

        {state === "ready" && error ? <div className="error-banner">{error}</div> : null}

        {state === "ready" ? (
          <section className="category-page-header">
            <div>
              <h1>Partners</h1>
              <p>Manage partner organizations and the users who can publish servers for them.</p>
            </div>
            <Link className="site-nav-cta" href="/partners/create">
              Create Partner
            </Link>
          </section>
        ) : null}

        {state === "ready" && partners.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No partners</div>
            <div className="empty-detail">No active partner organizations are listed.</div>
          </div>
        ) : null}

        {state === "ready" && partners.length > 0 ? (
          <div className="partner-table">
            <div className="partner-table-header">
              <span>Organization</span>
              <span>Status</span>
              <span>Tier</span>
              <span>Support</span>
              <span>Updated</span>
              <span />
            </div>
            {partners.map((partner) => (
              <div className="partner-table-row" key={partner.id}>
                <div className="partner-organization-cell">
                  <span className="partner-organization-icon" aria-hidden="true">
                    {partner.iconUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img alt="" src={partner.iconUrl} />
                    ) : (
                      partner.name.slice(0, 1).toUpperCase()
                    )}
                  </span>
                  <span>
                    <strong>{partner.name}</strong>
                    <small>{partner.slug}</small>
                  </span>
                </div>
                <span>{partner.partnerStatus}</span>
                <span>{partner.partnerTier}</span>
                <span>{partner.partnerSupportLevel}</span>
                <span>{formatDate(partner.updatedAt)}</span>
                <div className="partner-row-actions">
                  <Link className="partner-row-action" href={`/partners/${partner.id}/edit`}>
                    Edit
                  </Link>
                  <button
                    className="partner-row-action danger"
                    disabled={deletingPartnerId === partner.id}
                    onClick={() => void deletePartner(partner)}
                    type="button"
                  >
                    {deletingPartnerId === partner.id ? "Deleting" : "Delete"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
