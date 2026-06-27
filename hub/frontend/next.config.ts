import type { NextConfig } from "next";

const apiProxyTarget = process.env.WARDN_HUB_API_INTERNAL_BASE_URL ?? "http://localhost:8000";
const privatePaths = [
  "account",
  "api",
  "audit",
  "login",
  "partners",
  "register",
  "submit",
  "submissions",
];
const noindexHeaders = [
  {
    key: "X-Robots-Tag",
    value: "noindex, nofollow",
  },
];

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.1.101"],
  devIndicators: false,
  output: "standalone",
  async headers() {
    return [
      {
        headers: [
          {
            key: "Link",
            value:
              '</llms.txt>; rel="service-doc"; type="text/plain", </sitemap.xml>; rel="sitemap"; type="application/xml"',
          },
        ],
        source: "/(.*)",
      },
      ...privatePaths.flatMap((path) => [
        { headers: noindexHeaders, source: `/${path}` },
        { headers: noindexHeaders, source: `/${path}/:path*` },
      ]),
      {
        headers: [
          {
            key: "X-Robots-Tag",
            value: "noindex",
          },
        ],
        source: "/_next/:path*",
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget.replace(/\/+$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
