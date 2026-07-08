import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

export type BreadcrumbItem = {
  label: string;
  href?: string;
  current?: boolean;
};

type BreadcrumbProps = {
  items: BreadcrumbItem[];
  className?: string;
};

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav
      className={cn("flex items-center gap-2 text-xs text-[var(--el-text-secondary)]", className)}
      aria-label="面包屑导航"
    >
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`} className="flex items-center gap-2">
            {i > 0 && (
              <ChevronRight
                className="size-3 shrink-0 text-[var(--el-text-placeholder)]"
                aria-hidden
              />
            )}
            {item.href && !isLast ? (
              <Link
                href={item.href}
                className="transition-colors hover:text-[var(--el-primary)]"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={cn(isLast && "font-semibold text-[var(--el-text-regular)]")}
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
