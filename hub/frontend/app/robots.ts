import type { MetadataRoute } from "next";

import { resolveSiteUrl } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = resolveSiteUrl();
  const host = new URL(siteUrl).host;
  const publicAllowRule = {
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
      "/_next/",
    ],
  };

  return {
    host,
    rules: [
      {
        ...publicAllowRule,
        userAgent: "*",
      },
      {
        ...publicAllowRule,
        userAgent: "OAI-SearchBot",
      },
      {
        ...publicAllowRule,
        userAgent: "GPTBot",
      },
      {
        ...publicAllowRule,
        userAgent: "PerplexityBot",
      },
      {
        ...publicAllowRule,
        userAgent: "ClaudeBot",
      },
      {
        ...publicAllowRule,
        userAgent: "Googlebot",
      },
      {
        ...publicAllowRule,
        userAgent: "Bingbot",
      },
    ],
    sitemap: [`${siteUrl}/sitemap.xml`],
  };
}
