"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { listPartnerOrganizations, updatePartnerOrganization } from "@/lib/api/hub";
import type { PartnerOrganizationRead } from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
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
      listPartnerOrganizations()
        .then((response) => {
          setPartners(response.organizations);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load partners.");
          setState("error");
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
        <section className="category-page-header">
          <div>
            <h1>Partners</h1>
            <p>Manage partner organizations and the users who can publish servers for them.</p>
          </div>
          <Link className="site-nav-cta" href="/partners/create">
            Create Partner
          </Link>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching partner organizations.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Partners unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && error ? <div className="error-banner">{error}</div> : null}

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
                <div>
                  <strong>{partner.name}</strong>
                  <small>{partner.slug}</small>
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
