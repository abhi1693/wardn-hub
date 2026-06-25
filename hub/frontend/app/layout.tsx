import "./globals.css";

import type { ReactNode } from "react";

import { DeferredGoogleAnalytics } from "@/components/analytics/deferred-google-analytics";
import { AuthProvider } from "@/components/auth-provider";

const defaultGoogleAnalyticsId = "G-GYYSYTBZTD";

function googleAnalyticsId() {
  if (process.env.NODE_ENV !== "production") return "";
  return process.env.GOOGLE_ANALYTICS_ID?.trim() || defaultGoogleAnalyticsId;
}

export default function RootLayout({ children }: { children: ReactNode }) {
  const gaId = googleAnalyticsId();

  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
        {gaId ? <DeferredGoogleAnalytics gaId={gaId} /> : null}
      </body>
    </html>
  );
}
