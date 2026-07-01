"use client";

import { useEffect } from "react";
import { faro, getWebInstrumentations, initializeFaro } from "@grafana/faro-web-sdk";
import { TracingInstrumentation } from "@grafana/faro-web-tracing";

let faroInitialized = false;
let faroActionTrackingInitialized = false;

const ACTION_SELECTOR =
  'button, a[href], input[type="button"], input[type="submit"], input[type="reset"], [role="button"], [role="link"]';
const USER_ACTION_FALLBACK_END_DELAY_MS = 1200;

function installFaroUserActionTracking() {
  if (faroActionTrackingInitialized || typeof document === "undefined") {
    return;
  }

  faroActionTrackingInitialized = true;
  document.addEventListener("pointerdown", handleFaroUserAction, {
    capture: true,
  });
  document.addEventListener("keydown", handleFaroUserAction, {
    capture: true,
  });
  document.addEventListener("click", handleFaroNavigationClick, {
    capture: true,
  });
}

function handleFaroUserAction(event: Event) {
  if (
    event instanceof KeyboardEvent &&
    event.key !== "Enter" &&
    event.key !== " "
  ) {
    return;
  }

  if (!(event.target instanceof Element)) {
    return;
  }

  const element = event.target.closest<HTMLElement>(ACTION_SELECTOR);

  if (!element || element.dataset.faroUserActionName) {
    return;
  }

  const actionName = getFaroUserActionName(element);

  if (!actionName || faro.api.getActiveUserAction()) {
    return;
  }

  const userAction = faro.api.startUserAction(
    actionName,
    getFaroUserActionAttributes(element),
    {
      triggerName: event.type,
    },
  );

  scheduleFaroUserActionEnd(userAction);
}

function handleFaroNavigationClick(event: MouseEvent) {
  if (!(event.target instanceof Element)) {
    return;
  }

  const element = event.target.closest<HTMLElement>(ACTION_SELECTOR);

  if (!(element instanceof HTMLAnchorElement)) {
    return;
  }

  window.queueMicrotask(endActiveFaroUserAction);
}

function endActiveFaroUserAction() {
  const activeUserAction = faro.api.getActiveUserAction();

  (activeUserAction as typeof activeUserAction & { end?: () => void } | undefined)?.end?.();
}

function scheduleFaroUserActionEnd(
  userAction: ReturnType<typeof faro.api.startUserAction>,
) {
  if (!userAction) {
    return;
  }

  window.setTimeout(() => {
    const activeUserAction = faro.api.getActiveUserAction();

    if (activeUserAction !== userAction) {
      return;
    }

    endActiveFaroUserAction();
  }, USER_ACTION_FALLBACK_END_DELAY_MS);
}

function getFaroUserActionName(element: HTMLElement) {
  const explicitName = element.dataset.faroUserActionName?.trim();

  if (explicitName) {
    return explicitName;
  }

  const label =
    element.getAttribute("aria-label") ||
    element.getAttribute("title") ||
    element.innerText ||
    element.textContent ||
    element.getAttribute("name") ||
    element.id ||
    (element instanceof HTMLAnchorElement ? getFaroTargetPath(element) : "");
  const slug = toFaroActionSlug(label);

  if (!slug) {
    return undefined;
  }

  return `${getFaroElementRole(element)}-${slug}`;
}

function getFaroUserActionAttributes(element: HTMLElement) {
  const attributes: Record<string, string> = {
    elementRole: getFaroElementRole(element),
    pagePath: normalizeFaroPath(window.location.pathname),
  };
  const targetPath = getFaroTargetPath(element);

  if (targetPath) {
    attributes.targetPath = targetPath;
  }

  return attributes;
}

function getFaroElementRole(element: HTMLElement) {
  if (element instanceof HTMLAnchorElement) {
    return "navigate";
  }

  if (element instanceof HTMLInputElement && element.type === "submit") {
    return "submit";
  }

  return "click";
}

function getFaroTargetPath(element: HTMLElement) {
  if (!(element instanceof HTMLAnchorElement)) {
    return undefined;
  }

  try {
    return normalizeFaroPath(new URL(element.href, window.location.href).pathname);
  } catch {
    return undefined;
  }
}

function normalizeFaroPath(pathname: string) {
  return (
    pathname
      .split("/")
      .map((segment) =>
        /^\d+$/.test(segment) || /^[0-9a-f-]{8,}$/i.test(segment) ? ":id" : segment,
      )
      .join("/") || "/"
  );
}

function toFaroActionSlug(value: string | undefined) {
  return value
    ?.trim()
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

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
    installFaroUserActionTracking();
  }, []);

  return null;
}
