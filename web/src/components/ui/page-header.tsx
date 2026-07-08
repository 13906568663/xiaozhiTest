"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { useMenuBreadcrumb } from "@/lib/menu-context";

import { Breadcrumb, type BreadcrumbItem } from "./breadcrumb";

type PageHeaderProps = {
  title: string;
  description?: string;
  breadcrumb?: BreadcrumbItem[];
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({ title, description, breadcrumb, actions, className }: PageHeaderProps) {
  const resolvedBreadcrumb = useMenuBreadcrumb(breadcrumb);

  let resolvedTitle = title;
  if (
    breadcrumb && breadcrumb.length >= 2 &&
    resolvedBreadcrumb && resolvedBreadcrumb.length >= 2 &&
    title === breadcrumb[1].label
  ) {
    resolvedTitle = resolvedBreadcrumb[1].label;
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {resolvedBreadcrumb && resolvedBreadcrumb.length > 0 && (
        <Breadcrumb items={resolvedBreadcrumb} />
      )}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-[22px] font-semibold leading-tight text-[var(--el-text-primary)]">
            {resolvedTitle}
          </h1>
          {description && (
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--el-text-secondary)]">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2.5">{actions}</div>}
      </div>
    </div>
  );
}
