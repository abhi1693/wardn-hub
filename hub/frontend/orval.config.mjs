import { defineConfig } from "orval";

export default defineConfig({
  wardnHubApi: {
    input: {
      target: "./openapi/wardn-hub-api.json",
    },
    output: {
      mode: "tags-split",
      target: "./lib/api/generated/wardn-hub.ts",
      schemas: "./lib/api/generated/model",
      client: "fetch",
      clean: true,
      baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    },
  },
});

