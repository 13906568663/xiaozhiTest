import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type ContentCardProps = {
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
};

export function ContentCard({ children, className, noPadding }: ContentCardProps) {
  return (
    <div
      className={cn(
        "rounded border border-[var(--el-border-lighter)] bg-[var(--el-fill-blank)]",
        !noPadding && "p-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
