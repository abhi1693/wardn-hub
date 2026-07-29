export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => isRecord(item))
    : [];
}

function toolCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = toolCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.tools)) return [records(value.tools)];
  return [];
}

function promptCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = promptCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.prompts)) return [records(value.prompts)];
  return [];
}

function resourceCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = resourceCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.resources)) return [records(value.resources)];
  return [];
}

function resourceTemplateCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = resourceTemplateCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.resourceTemplates)) return [records(value.resourceTemplates)];
  return [];
}

export function toolsFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.tools,
    serverJson.toolDefinitions,
    serverJson.mcpTools,
    capabilities.tools,
    introspection.tools,
    introspection["tools/list"],
    serverJson["tools/list"],
    mcp.tools,
    mcp["tools/list"],
    meta.tools,
    metaCapabilities.tools,
    metaIntrospection.tools,
    metaIntrospection["tools/list"],
    metaMcp.tools,
    metaMcp["tools/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(toolCandidateLists)
    .flat()
    .filter((tool) => {
      const name = typeof tool.name === "string" ? tool.name.trim() : "";
      if (!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
}

export function promptsFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.prompts,
    serverJson.promptDefinitions,
    serverJson.mcpPrompts,
    capabilities.prompts,
    introspection.prompts,
    introspection["prompts/list"],
    serverJson["prompts/list"],
    mcp.prompts,
    mcp["prompts/list"],
    meta.prompts,
    metaCapabilities.prompts,
    metaIntrospection.prompts,
    metaIntrospection["prompts/list"],
    metaMcp.prompts,
    metaMcp["prompts/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(promptCandidateLists)
    .flat()
    .filter((prompt) => {
      const name = typeof prompt.name === "string" ? prompt.name.trim() : "";
      if (!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
}

export function resourcesFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.resources,
    serverJson.resourceDefinitions,
    serverJson.mcpResources,
    capabilities.resources,
    introspection.resources,
    introspection["resources/list"],
    serverJson["resources/list"],
    mcp.resources,
    mcp["resources/list"],
    meta.resources,
    metaCapabilities.resources,
    metaIntrospection.resources,
    metaIntrospection["resources/list"],
    metaMcp.resources,
    metaMcp["resources/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(resourceCandidateLists)
    .flat()
    .filter((resource) => {
      const uri = typeof resource.uri === "string" ? resource.uri.trim() : "";
      if (!uri || seen.has(uri)) return false;
      seen.add(uri);
      return true;
    });
}

export function resourceTemplatesFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.resourceTemplates,
    serverJson.resourceTemplateDefinitions,
    serverJson["resources/templates/list"],
    introspection.resourceTemplates,
    introspection["resources/templates/list"],
    mcp.resourceTemplates,
    mcp["resources/templates/list"],
    meta.resourceTemplates,
    meta["resources/templates/list"],
    metaIntrospection.resourceTemplates,
    metaIntrospection["resources/templates/list"],
    metaMcp.resourceTemplates,
    metaMcp["resources/templates/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(resourceTemplateCandidateLists)
    .flat()
    .filter((template) => {
      const uriTemplate =
        typeof template.uriTemplate === "string" ? template.uriTemplate.trim() : "";
      if (!uriTemplate || seen.has(uriTemplate)) return false;
      seen.add(uriTemplate);
      return true;
    });
}
