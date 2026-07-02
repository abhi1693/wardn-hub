import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublicHeader } from "@/components/site-header";
import {
  getProgrammaticPageData,
  ProgrammaticLandingPage,
  programmaticPageForSlug,
  programmaticPagesForKind,
} from "@/lib/programmatic-pages";
import { siteConfig } from "@/lib/site";

export const revalidate = 3600;

type IntegrationPageProps = {
  params: Promise<{ integrationSlug?: string }>;
};

export function generateStaticParams() {
  return programmaticPagesForKind("integration").map((page) => ({
    integrationSlug: page.slug,
  }));
}

export async function generateMetadata({ params }: IntegrationPageProps): Promise<Metadata> {
  const { integrationSlug = "" } = await params;
  const config = programmaticPageForSlug("integration", integrationSlug);
  if (!config) return {};

  return {
    alternates: {
      canonical: config.path,
    },
    description: config.description,
    openGraph: {
      description: config.description,
      title: `${config.title} | ${siteConfig.name}`,
      url: config.path,
    },
    title: config.title,
    twitter: {
      card: "summary",
      description: config.description,
      title: `${config.title} | ${siteConfig.name}`,
    },
  };
}

export default async function IntegrationPage({ params }: IntegrationPageProps) {
  const { integrationSlug = "" } = await params;
  const config = programmaticPageForSlug("integration", integrationSlug);
  if (!config) notFound();

  const data = await getProgrammaticPageData(config);

  return (
    <div className="server-detail-page">
      <PublicHeader />
      <ProgrammaticLandingPage config={config} data={data} />
    </div>
  );
}
