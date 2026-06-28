import { LoaderCircle } from "lucide-react";

export function PageLoader({
  className = "",
  compact = false,
  label = "Loading",
}: {
  className?: string;
  compact?: boolean;
  label?: string;
}) {
  const classes = [
    compact ? "grid min-h-24 place-items-center p-4" : "grid min-h-[190px] place-items-center p-6",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div aria-label={label} className={classes} role="status">
      <LoaderCircle aria-hidden="true" className="size-7 animate-spin text-muted-foreground" />
    </div>
  );
}
