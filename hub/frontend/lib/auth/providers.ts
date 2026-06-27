export function clientAuthProviders() {
  return (process.env.NEXT_PUBLIC_AUTH_PROVIDERS ?? "local")
    .split(",")
    .map((provider) => provider.trim().toLowerCase())
    .filter(Boolean);
}

export function clerkPublishableKey() {
  return process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
}

export function isClerkProviderEnabled() {
  return clientAuthProviders().includes("clerk");
}

export function isClerkConfigured() {
  return Boolean(clerkPublishableKey());
}

export function isClerkEnabled() {
  return isClerkProviderEnabled() && isClerkConfigured();
}
