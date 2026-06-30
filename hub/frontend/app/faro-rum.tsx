"use client";

import { useEffect } from "react";
import { getWebInstrumentations, initializeFaro } from "@grafana/faro-web-sdk";
import { TracingInstrumentation } from "@grafana/faro-web-tracing";

let faroInitialized = false;

export function FaroRum() {
  useEffect(() => {
    if (faroInitialized || process.env.NEXT_PUBLIC_FARO_ENABLED !== "true") {
      return;
    }

    const url = process.env.NEXT_PUBLIC_FARO_URL?.trim();
    const apiKey = process.env.NEXT_PUBLIC_FARO_API_KEY?.trim();

    if (!url || !apiKey) {
      return;
    }

    faroInitialized = true;

    initializeFaro({
      url,
      apiKey,
      app: {
        name: process.env.NEXT_PUBLIC_FARO_APP_NAME || "wardn-hub",
        version: process.env.NEXT_PUBLIC_FARO_APP_VERSION || undefined,
        environment: process.env.NEXT_PUBLIC_FARO_ENVIRONMENT || "production",
      },
      instrumentations: [
        ...getWebInstrumentations(),
        new TracingInstrumentation(),
      ],
    });
  }, []);

  return null;
}
