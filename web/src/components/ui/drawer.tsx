"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: string | number;
  className?: string;
};

export function Drawer({ open, onClose, title, children, footer, width = 480, className }: DrawerProps) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-[var(--el-bg-overlay)]"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={cn(
          "fixed top-0 right-0 z-50 flex h-full flex-col bg-[var(--el-fill-blank)] shadow-[-2px_0_20px_rgba(0,0,0,0.1)] transition-transform duration-300",
          open ? "translate-x-0" : "translate-x-full",
          className,
        )}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between border-b border-[var(--el-border-lighter)] px-6 py-5">
          <h2 className="text-[17px] font-semibold text-[var(--el-text-primary)]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-md text-[var(--el-text-placeholder)] transition-colors hover:bg-[var(--el-color-info-bg)] hover:text-[var(--el-text-regular)]"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-[var(--el-border-lighter)] px-6 py-4">
            {footer}
          </div>
        )}
      </aside>
    </>
  );
}
