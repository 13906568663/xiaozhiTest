import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type LoginCardProps = {
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function LoginCard({ title, description, children, className }: LoginCardProps) {
  return (
    <div
      className={cn(
        "w-full max-w-[400px] rounded border border-[var(--el-border-lighter)] bg-[var(--el-fill-blank)] p-8 shadow-[0_1px_4px_rgba(0,0,0,0.06)]",
        className,
      )}
    >
      {(title || description) && (
        <div className="mb-8 space-y-2 text-center">
          {title && (
            <h1 className="text-xl font-semibold tracking-tight text-[var(--el-text-primary)]">
              {title}
            </h1>
          )}
          {description && (
            <p className="text-sm text-[var(--el-text-secondary)]">{description}</p>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
