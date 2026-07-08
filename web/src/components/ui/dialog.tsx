"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: string | number;
  className?: string;
};

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 540,
  className,
}: DialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-[var(--el-bg-overlay)]"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cn(
          "relative z-10 flex max-h-[85vh] flex-col rounded-xl bg-[var(--el-fill-blank)] shadow-2xl",
          className,
        )}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between border-b border-[var(--el-border-lighter)] px-5 py-4">
          <div>
            <h2 className="text-[17px] font-semibold text-[var(--el-text-primary)]">{title}</h2>
            {description && (
              <p className="mt-0.5 text-[11px] text-[var(--el-text-secondary)]">{description}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-md text-[var(--el-text-placeholder)] transition-colors hover:bg-[var(--el-color-info-bg)] hover:text-[var(--el-text-regular)]"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 thin-scrollbar">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2.5 border-t border-[var(--el-border-lighter)] px-5 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
