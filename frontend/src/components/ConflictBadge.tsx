"use client";

import { ConflictType } from "@/types";

interface ConflictBadgeProps {
  conflictType: ConflictType;
  size?: "sm" | "md";
}

const conflictConfig: Record<
  ConflictType,
  { label: string; bgClass: string; textClass: string; dotClass: string }
> = {
  CONCEPTUAL: {
    label: "Conceptual Conflict",
    bgClass: "bg-red-900/50 border border-red-700",
    textClass: "text-red-300",
    dotClass: "bg-red-500",
  },
  METHODOLOGY: {
    label: "Methodology",
    bgClass: "bg-orange-900/50 border border-orange-700",
    textClass: "text-orange-300",
    dotClass: "bg-orange-500",
  },
  ASSAY_VARIABILITY: {
    label: "Assay Variability",
    bgClass: "bg-yellow-900/50 border border-yellow-700",
    textClass: "text-yellow-800 dark:text-yellow-200",
    dotClass: "bg-yellow-500",
  },
  EVOLVING_DATA: {
    label: "Evolving Data",
    bgClass: "bg-blue-900/50 border border-blue-700",
    textClass: "text-blue-300",
    dotClass: "bg-blue-500",
  },
  NON_CONFLICT: {
    label: "Non-Conflict",
    bgClass: "bg-green-900/50 border border-green-700",
    textClass: "text-green-300",
    dotClass: "bg-green-500",
  },
};

export default function ConflictBadge({
  conflictType,
  size = "md",
}: ConflictBadgeProps) {
  const config = conflictConfig[conflictType];

  const sizeClasses =
    size === "sm"
      ? "px-2 py-0.5 text-xs gap-1"
      : "px-2.5 py-1 text-xs gap-1.5";

  const dotSizeClass = size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2";

  return (
    <span
      data-testid="conflict-badge"
      data-conflict-type={conflictType}
      className={`inline-flex items-center rounded-full font-medium ${config.bgClass} ${config.textClass} ${sizeClasses}`}
    >
      <span
        className={`${dotSizeClass} rounded-full ${config.dotClass} flex-shrink-0`}
      />
      {config.label}
    </span>
  );
}
