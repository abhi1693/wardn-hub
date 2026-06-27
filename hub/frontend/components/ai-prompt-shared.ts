export function currentApiBaseUrl() {
  if (typeof window === "undefined") return "/api/v1";
  return `${window.location.origin}/api/v1`;
}

export async function copyText(value: string, target?: HTMLTextAreaElement | null) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Clipboard can be exposed but blocked on non-secure origins.
  }

  const textarea = target ?? document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  if (!target) {
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
  }

  try {
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand("copy");
    if (!copied) throw new Error("copy command failed");
  } finally {
    if (!target) document.body.removeChild(textarea);
  }
}

export const API_ACCESS_INSTRUCTIONS = `Required API access:
- Use WARDN_HUB_TOKEN as the Wardn Hub bearer token.
- If WARDN_HUB_TOKEN is not available in the environment or context, stop and ask the user for a Wardn Hub API token.
- Do not call the Wardn Hub API until a token is available.`;

export const REGISTRY_METADATA_SCOPE_RULE = `Treat this as registry metadata review only. Do not install workspace MCP servers, invoke MCP tools, or manage runtime infrastructure.`;

export const PACKAGE_AND_REMOTE_RULES = `Package and remote rules:
- If the server is installed through npm, PyPI/uvx, Docker/OCI, or another package registry, add packages[] with registryType, identifier, version when known, and transport.
- Split versions from package identifiers. Do not put versions or tags inside identifiers.
- If the server is hosted remotely over HTTP/SSE/streamable HTTP and users connect to a URL instead of installing a package, add remotes[] instead of inventing a package target.
- Preserve documented command, args, transport type, env, and endpoint paths exactly enough for a user to configure the server.
- Remote endpoint URLs must not include configurable query strings such as ?apiKey={apiKey}. Put those parameters in remotes[].queryParameters instead.
- Use remotes[].queryParameters for remote URL query parameters. Do not put query parameters under remotes[].authentication.queryParameters.`;

export const REMOTE_QUERY_PARAMETER_RULES = `Remote query parameter rules:
- Remote endpoint URLs must be the base endpoint path only, without configurable query strings.
- Put remote query parameters in remotes[].queryParameters with name, description, isRequired, and isSecret.
- Do not put query parameters under remotes[].authentication.queryParameters.
- For docs that show "https://example.com/mcp?apiKey={apiKey}", use {"url":"https://example.com/mcp","queryParameters":[{"name":"apiKey","isRequired":true,"isSecret":true}]}.`;

export const PACKAGE_ARGUMENT_RULES = `Package argument rules:
- packages[].transport.args must be the runnable default launch arguments only. Do not add every documented CLI option there.
- Add only arguments that must always be present for the documented default launch to packages[].transport.args, preserving order exactly.
- Optional CLI flags/configurable arguments belong in packages[].packageArguments with includeInLaunch false.
- Use packageArguments[].requiresValue true when a flag takes a user-supplied value. Do not include placeholder text like <port> or [url] in transport.args.
- requiresValue is a boolean. Do not set packageArguments[].value to placeholder examples such as "<host>", "[url]", "host", or "url".
- Do not include placeholders inside packageArguments[].flag. For docs that show "--host <host>", use {"flag":"--host","requiresValue":true,"includeInLaunch":false}.
- If a package argument is part of the default launch command, set includeInLaunch true. Otherwise leave it false.`;

export const ENVIRONMENT_VARIABLE_RULES = `Environment variable rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Use documented non-secret defaults when available.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.
- Add every documented environment variable to serverJson._meta.sourceReview.llm.environmentVariables, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- If an env var belongs in runtime launch config, add it to packages[].transport.env with a safe value.`;

export const ENVIRONMENT_REVIEW_RULES = `Environment variable review:
- Read README/docs for every environment variable and CLI option.
- Do not only copy variables returned by import API.
- Add every documented environment variable to sourceReview.llm.environmentVariables.
- If an environment variable belongs in runtime launch config, add it to packages[].transport.env.
- Use documented non-secret defaults when available.
- If you intentionally exclude a variable from packages[].transport.env, still include it in sourceReview.llm.environmentVariables with source and reason.`;

export const SOURCE_REVIEW_EVIDENCE_REQUIREMENTS = `LLM source review evidence must be stored under serverJson._meta.sourceReview.llm and include:
- sourceReview.llm.filesRead
- sourceReview.llm.installCommands
- sourceReview.llm.commandArguments
- sourceReview.llm.environmentVariables
- sourceReview.llm.prerequisites
- sourceReview.llm.capabilitiesReviewed = true
- sourceReview.llm.limitationsReviewed = true
- sourceReview.llm.unknowns = []`;

export const SOURCE_REVIEW_LIST_FORMAT = `Source review list format:
- filesRead, installCommands, commandArguments, and prerequisites must be readable strings or objects with at least one of: flag, name, value, default, description.
- Do not put arbitrary nested objects in commandArguments. For CLI options, prefer strings such as "--stdio" or objects like {"flag":"--port","requiresValue":true,"description":"Port for HTTP transport."}.
- Do not write LLM-generated review evidence into flat sourceReview fields; use sourceReview.llm so it is distinguishable from human review evidence.`;

export const DRAFT_METADATA_RULES = `Metadata rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.
- Split package versions from identifiers. Do not put versions or tags inside package identifiers.
- Ensure package transport command, args, env, and type match documented install/run instructions.
${PACKAGE_ARGUMENT_RULES}
${REMOTE_QUERY_PARAMETER_RULES}
- Ensure documentation, title, description, websiteUrl, repository, packages/remotes, icons, and version are accurate where available.`;

export const VALIDATION_PACKAGE_ARGUMENT_CHECKS = `- packages[].transport.args contains only the concrete default launch arguments in runnable order, not every documented optional CLI flag.
- Optional CLI flags/configurable arguments are represented in packages[].packageArguments with includeInLaunch false.
- Flags that take user-supplied values are represented with packageArguments[].requiresValue true, not placeholder text in transport.args.
- packageArguments[].value does not contain placeholder examples such as "<host>", "[url]", "host", or "url"; requiresValue is the metadata for that.
- packageArguments[].flag does not contain placeholders. For docs that show "--host <host>", the correct shape is flag "--host" and requiresValue true.
- Package arguments that are part of the default launch command have includeInLaunch true.`;

export const VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS = `- Remote endpoint URLs do not include configurable query strings such as ?apiKey={apiKey}.
- Remote URL query parameters are represented in remotes[].queryParameters, not remotes[].authentication.queryParameters.
- If docs show a hosted URL with query authentication, the base endpoint is stored in remotes[].url and the query auth fields are stored in remotes[].queryParameters.`;
