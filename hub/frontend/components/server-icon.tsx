"use client";

import { Server } from "lucide-react";
import { useEffect, useState } from "react";

import type { RegistryServerRead } from "@/lib/api/generated/model";

export function serverIconUrl(server: RegistryServerRead) {
  const icon = server.icons?.find((item) => {
    const src = typeof item.src === "string" ? item.src : "";
    const url = typeof item.url === "string" ? item.url : "";
    return Boolean(src || url);
  });
  if (!icon) return "";
  return typeof icon.src === "string" ? icon.src : typeof icon.url === "string" ? icon.url : "";
}

function cssUrl(value: string) {
  return `url(${JSON.stringify(value)})`;
}

export function ServerIcon({ src, title }: { src: string; title: string }) {
  const [failedSrc, setFailedSrc] = useState("");

  useEffect(() => {
    if (!src) return;
    const image = new window.Image();
    image.onerror = () => setFailedSrc(src);
    image.src = src;
  }, [src]);

  if (src && failedSrc !== src) {
    return (
      <span
        className="server-card-icon server-card-icon-image"
        style={{ backgroundImage: cssUrl(src) }}
      />
    );
  }

  return (
    <span className="server-card-icon" aria-label={`${title} icon`}>
      <Server size={22} />
    </span>
  );
}
