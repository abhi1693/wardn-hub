import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DeferredGoogleAnalytics } from "@/components/analytics/deferred-google-analytics";
import { AuthProvider } from "@/components/auth-provider";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, websiteJsonLd } from "@/lib/structured-data";

const defaultGoogleAnalyticsId = "G-GYYSYTBZTD";

function googleAnalyticsId() {
  if (process.env.NODE_ENV !== "production") return "";
  return process.env.GOOGLE_ANALYTICS_ID?.trim() || defaultGoogleAnalyticsId;
}

export const metadata: Metadata = {
  description: siteConfig.description,
  keywords: [...siteConfig.keywords],
  metadataBase: new URL(siteConfig.url),
  openGraph: {
    description: siteConfig.description,
    locale: "en_US",
    siteName: siteConfig.name,
    title: siteConfig.tagline,
    type: "website",
    url: siteConfig.url,
  },
  robots: {
    follow: true,
    index: true,
  },
  title: {
    default: `${siteConfig.name} - ${siteConfig.tagline}`,
    template: `%s | ${siteConfig.name}`,
  },
  twitter: {
    card: "summary",
    description: siteConfig.description,
    title: siteConfig.tagline,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const gaId = googleAnalyticsId();

  return (
    <html lang="en">
      <body>
        <JsonLdScript data={websiteJsonLd()} id="website-json-ld" />
        <AuthProvider>{children}</AuthProvider>
        {gaId ? <DeferredGoogleAnalytics gaId={gaId} /> : null}
      </body>
    </html>
  );
}
