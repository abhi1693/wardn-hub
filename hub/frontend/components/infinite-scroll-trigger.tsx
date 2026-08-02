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
  const requestedRef = useRef(false);

  useEffect(() => {
    if (!loading) requestedRef.current = false;
  }, [loading]);

  if (!hasMore && !error) return null;

  return (
    <div className="server-grid-more" data-load-more-trigger>
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
