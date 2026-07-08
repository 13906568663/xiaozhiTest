"use client";

import type { ReactNode } from "react";
import { Bot } from "lucide-react";

import { cn } from "@/lib/utils";

export type AdminHeaderProps = {
  brandTitle?: ReactNode;
  logo?: ReactNode;
  className?: string;
  children?: ReactNode;
};

const defaultLogo = (
  <div
    className="flex size-[var(--admin-logo-box)] shrink-0 items-center justify-center rounded-[var(--admin-logo-radius)] bg-[var(--el-primary)]"
    aria-hidden
  >
    <Bot className="size-[18px] text-white" strokeWidth={2} />
  </div>
);

export function AdminHeader({
  brandTitle = "智能体任务调度平台",
  logo = defaultLogo,
  className,
  children,
}: AdminHeaderProps) {
  return (
    <header
      className={cn(
        "flex h-[var(--admin-topbar-h)] shrink-0 items-center justify-between gap-4 border-b border-[var(--el-border-lighter)] bg-[var(--el-fill-blank)] py-0 pr-6 pl-4",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        {logo}
        <span className="truncate text-sm font-semibold text-[var(--el-text-primary)]">
          {brandTitle}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-5 text-xs text-[var(--el-text-regular)]">
        {children}
      </div>
    </header>
  );
}
