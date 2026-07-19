import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DeferredGoogleAnalytics } from "@/components/analytics/deferred-google-analytics";
import { SiteFooter } from "@/components/site-footer";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, websiteJsonLd } from "@/lib/structured-data";
import { FaroRum } from "./faro-rum";

const defaultGoogleAnalyticsId = "G-GYYSYTBZTD";

function googleAnalyticsId() {
  if (process.env.NODE_ENV !== "production") return "";
  return process.env.GOOGLE_ANALYTICS_ID?.trim() || defaultGoogleAnalyticsId;
}

export const metadata: Metadata = {
  applicationName: siteConfig.name,
  description: siteConfig.description,
  icons: {
    apple: [{ sizes: "180x180", type: "image/png", url: "/wardn-brand-180x180.png" }],
    icon: [
      { url: "/wardn-brand-favicon.ico" },
      { sizes: "16x16", type: "image/png", url: "/wardn-brand-16x16.png" },
      { sizes: "32x32", type: "image/png", url: "/wardn-brand-32x32.png" },
    ],
    shortcut: ["/wardn-brand-favicon.ico"],
  },
  keywords: [...siteConfig.keywords],
  manifest: "/wardn-brand.webmanifest",
  metadataBase: new URL(siteConfig.url),
  openGraph: {
    description: siteConfig.description,
    images: [
      {
        alt: siteConfig.name,
        height: 630,
        url: "/og-image.png",
        width: 1200,
      },
    ],
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
    card: "summary_large_image",
    description: siteConfig.description,
    images: ["/og-image.png"],
    title: siteConfig.tagline,
  },
  other: {
    "msapplication-TileColor": "#0f172a",
    "msapplication-TileImage": "/wardn-brand-mstile-150x150.png",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const gaId = googleAnalyticsId();

  return (
    <html lang="en">
      <body>
        <FaroRum />
        <JsonLdScript data={websiteJsonLd()} id="website-json-ld" />
        {children}
        <SiteFooter />
        {gaId ? <DeferredGoogleAnalytics gaId={gaId} /> : null}
      </body>
    </html>
  );
}
