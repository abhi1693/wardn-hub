"use client";

import { useEffect, useRef } from "react";

export function InfiniteScrollTrigger({
  error,
  hasMore,
  loading,
  onLoadMore,
}: {
  error?: string;
  hasMore: boolean;
  loading: boolean;
  onLoadMore: () => Promise<void> | void;
}) {
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const requestedRef = useRef(false);

  useEffect(() => {
    if (!loading) requestedRef.current = false;
  }, [loading]);

  useEffect(() => {
    const trigger = triggerRef.current;
    if (!trigger || !hasMore || loading || error || !("IntersectionObserver" in window)) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting) || requestedRef.current) return;
        requestedRef.current = true;
        void onLoadMore();
      },
      { rootMargin: "400px 0px", threshold: 0 },
    );

    observer.observe(trigger);
    return () => observer.disconnect();
  }, [error, hasMore, loading, onLoadMore]);

  if (!hasMore && !error) return null;

  return (
    <div className="server-grid-more" data-infinite-scroll-trigger ref={triggerRef}>
      {error ? <p role="alert">{error}</p> : null}
      {hasMore ? (
        <button
          className="server-grid-load-more"
          disabled={loading}
          onClick={() => {
            if (requestedRef.current) return;
            requestedRef.current = true;
            void onLoadMore();
          }}
          type="button"
        >
          {loading ? "Loading more…" : error ? "Try again" : "Load more"}
        </button>
      ) : null}
      <span aria-live="polite" className="sr-only" role="status">
        {loading ? "Loading more results" : ""}
      </span>
    </div>
  );
}
