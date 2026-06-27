import type { MetadataRoute } from "next";

import { resolveSiteUrl } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = resolveSiteUrl();
  const host = new URL(siteUrl).host;

  return {
    host,
    rules: [
      {
        allow: "/",
        disallow: [
          "/account/",
          "/api/",
          "/audit",
          "/login",
          "/partners",
          "/register",
          "/submit",
          "/submissions",
          "/users",
          "/_next/",
        ],
        userAgent: "*",
      },
    ],
    sitemap: [`${siteUrl}/sitemap.xml`],
  };
}
