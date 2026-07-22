"use client";

import { LoaderCircle, Search, Server, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type FocusEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { serverDetailHref } from "@/components/server-card";
import { listPublishedServers } from "@/lib/api/hub";
import { skillDetailPath, searchPublicSkillsPage } from "@/lib/public-skills";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import { cn } from "@/lib/utils";

const AUTOCOMPLETE_DEBOUNCE_MS = 200;
const AUTOCOMPLETE_LIMIT = 4;

type CatalogSuggestion = {
  href: string;
  id: string;
  label: string;
  meta: string;
  type: "server" | "skill";
};

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

export function CatalogSearchForm({
  className,
  defaultValue = "",
  id,
}: {
  className?: string;
  defaultValue?: string;
  id: string;
}) {
  const router = useRouter();
  const listboxId = useId();
  const requestIdRef = useRef(0);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState(defaultValue);
  const [status, setStatus] = useState("");
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([]);
  const trimmedQuery = query.trim();
  const canSuggest = trimmedQuery.length >= 3;
  const showPopover = isOpen && canSuggest && (loading || Boolean(status) || suggestions.length > 0);
  const suggestionListOpen = isOpen && suggestions.length > 0;

  useEffect(() => {
    if (!isOpen || !canSuggest) {
      return undefined;
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setLoading(true);
      setStatus("");

      void Promise.allSettled([
        listPublishedServers(
          {
            fields: PUBLIC_CARD_FIELDS,
            limit: AUTOCOMPLETE_LIMIT,
            search: trimmedQuery,
          },
          { signal: controller.signal },
        ),
        searchPublicSkillsPage(
          { limit: AUTOCOMPLETE_LIMIT, query: trimmedQuery },
          { signal: controller.signal },
        ),
      ]).then(([serverResult, skillResult]) => {
        if (requestIdRef.current !== requestId || controller.signal.aborted) return;

        const serverSuggestions: CatalogSuggestion[] =
          serverResult.status === "fulfilled"
            ? serverResult.value.servers.map((server) => ({
                href: serverDetailHref(server.name),
                id: `server-${server.id}`,
                label: server.title || server.name,
                meta: server.name,
                type: "server",
              }))
            : [];
        const skillSuggestions: CatalogSuggestion[] =
          skillResult.status === "fulfilled"
            ? skillResult.value.skills.map((skill) => ({
                href: skillDetailPath(skill.id),
                id: `skill-${skill.id}`,
                label: skill.name,
                meta: skill.source,
                type: "skill",
              }))
            : [];
        const nextSuggestions = [...serverSuggestions, ...skillSuggestions];
        const failed = [serverResult, skillResult].filter(
          (result) =>
            result.status === "rejected" && !isAbortError(result.reason),
        ).length;

        setActiveIndex(-1);
        setSuggestions(nextSuggestions);
        setStatus(
          nextSuggestions.length > 0
            ? `${nextSuggestions.length} suggestion${nextSuggestions.length === 1 ? "" : "s"} available`
            : failed === 2
              ? "Suggestions are temporarily unavailable"
              : "No matching MCP servers or agent skills",
        );
        setLoading(false);
      });
    }, AUTOCOMPLETE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [canSuggest, isOpen, trimmedQuery]);

  function selectSuggestion(suggestion: CatalogSuggestion) {
    setIsOpen(false);
    setActiveIndex(-1);
    setLoading(false);
    router.push(suggestion.href);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setIsOpen(false);
      setActiveIndex(-1);
      setLoading(false);
      return;
    }

    if (!suggestions.length || !isOpen) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) =>
        current <= 0 ? suggestions.length - 1 : current - 1,
      );
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    }
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsOpen(false);
      setActiveIndex(-1);
      setLoading(false);
    }
  }

  return (
    <div className={cn("catalog-search-combobox", className)} onBlur={handleBlur}>
      <form
        action="/search"
        aria-busy={loading}
        className="home-search"
        method="get"
        onSubmit={() => {
          setIsOpen(false);
          setLoading(false);
        }}
        role="search"
      >
        {loading ? (
          <LoaderCircle aria-hidden="true" className="catalog-search-spinner" size={21} />
        ) : (
          <Search aria-hidden="true" size={21} />
        )}
        <label className="sr-only" htmlFor={id}>
          Search MCP servers and agent skills
        </label>
        <input
          aria-activedescendant={
            activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined
          }
          aria-autocomplete="list"
          aria-controls={suggestionListOpen ? listboxId : undefined}
          aria-expanded={suggestionListOpen}
          autoComplete="off"
          id={id}
          maxLength={200}
          minLength={3}
          name="q"
          onChange={(event) => {
            const nextQuery = event.currentTarget.value;
            setQuery(nextQuery);
            setIsOpen(true);
            setActiveIndex(-1);
            setLoading(nextQuery.trim().length >= 3);
            setStatus("");
            setSuggestions([]);
          }}
          onFocus={() => {
            setIsOpen(true);
            setLoading(canSuggest);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search MCP servers and agent skills"
          required
          role="combobox"
          type="search"
          value={query}
        />
        <button type="submit">Search</button>
      </form>

      {showPopover ? (
        <div className="catalog-search-popover">
          {loading ? (
            <div className="catalog-search-status" role="status">
              <LoaderCircle aria-hidden="true" className="catalog-search-spinner" size={17} />
              Searching both catalogs
            </div>
          ) : suggestions.length > 0 ? (
            <ul aria-label="Search suggestions" className="catalog-search-list" id={listboxId} role="listbox">
              {suggestions.map((suggestion, index) => (
                <li key={suggestion.id} role="presentation">
                  <button
                    aria-selected={activeIndex === index}
                    className={cn(
                      "catalog-search-option",
                      activeIndex === index && "active",
                    )}
                    id={`${listboxId}-option-${index}`}
                    onClick={() => selectSuggestion(suggestion)}
                    onMouseEnter={() => setActiveIndex(index)}
                    onPointerDown={(event) => event.preventDefault()}
                    role="option"
                    type="button"
                  >
                    <span
                      aria-hidden="true"
                      className={cn("catalog-search-option-icon", suggestion.type)}
                    >
                      {suggestion.type === "server" ? (
                        <Server size={17} />
                      ) : (
                        <Sparkles size={17} />
                      )}
                    </span>
                    <span className="catalog-search-option-copy">
                      <strong>{suggestion.label}</strong>
                      <small>{suggestion.meta}</small>
                    </span>
                    <span className="catalog-search-option-type">
                      {suggestion.type === "server" ? "MCP server" : "Agent skill"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="catalog-search-status" role="status">
              {status}
            </div>
          )}
          <span aria-live="polite" className="sr-only">
            {status}
          </span>
        </div>
      ) : null}
    </div>
  );
}
