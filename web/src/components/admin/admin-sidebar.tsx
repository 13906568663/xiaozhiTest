"use client";

import Link from "next/link";
import { ChevronDown } from "lucide-react";

import * as Collapsible from "@radix-ui/react-collapsible";

import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";

import type { NavSection } from "./nav-types";

export type AdminSidebarProps = {
  sections: NavSection[];
  /** Current path for active item (e.g. from usePathname()) */
  activePath?: string;
  className?: string;
};

function isActive(href: string, activePath: string | undefined): boolean {
  if (!activePath) return false;
  if (href === "/") return activePath === href;
  return activePath === href || activePath.startsWith(`${href}/`);
}

export function AdminSidebar({ sections, activePath, className }: AdminSidebarProps) {
  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-[var(--admin-sidebar-w)] shrink-0 flex-col border-r border-[var(--el-border-light)] bg-[var(--el-fill-blank)]",
        className,
      )}
    >
      <ScrollArea className="flex-1">
        <nav className="flex flex-col gap-3.5 py-5 px-4 pb-4" aria-label="主导航">
          {sections.map((section) => (
            <Collapsible.Root key={section.id} defaultOpen={section.defaultOpen ?? true}>
              <Collapsible.Trigger className="group flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-semibold text-[var(--el-text-secondary)] outline-none hover:text-[var(--el-text-regular)] [&[data-state=open]_svg]:rotate-180">
                <span>{section.title}</span>
                <ChevronDown
                  className="size-4 shrink-0 text-[var(--el-text-placeholder)] transition-transform duration-200"
                  aria-hidden
                />
              </Collapsible.Trigger>
              <Collapsible.Content className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
                <ul className="mt-0.5 flex flex-col gap-0.5 pt-1">
                  {section.items.map((item, idx) => {
                    const active = isActive(item.href, activePath);
                    const Icon = item.icon;
                    return (
                      <li key={`${section.id}-${item.href}-${idx}`}>
                        <Link
                          href={item.href}
                          className={cn(
                            "flex items-center gap-2.5 border-l-[3px] py-2.5 pr-3 pl-3 text-sm transition-colors",
                            active
                              ? "border-[var(--el-primary)] bg-[var(--el-fill-blank)] font-medium text-[var(--el-text-primary)]"
                              : "border-transparent text-[var(--el-text-regular)] hover:bg-[var(--el-color-info-bg)]/60",
                          )}
                        >
                          {Icon && (
                            <Icon
                              className={cn(
                                "size-4 shrink-0",
                                active ? "text-[var(--el-primary)]" : "text-[var(--el-text-secondary)]",
                              )}
                              aria-hidden
                            />
                          )}
                          <span className="truncate">{item.label}</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </Collapsible.Content>
            </Collapsible.Root>
          ))}
        </nav>
      </ScrollArea>
    </aside>
  );
}
