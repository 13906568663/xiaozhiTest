import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { AdminHeader, type AdminHeaderProps } from "./admin-header";
import { AdminSidebar, type AdminSidebarProps } from "./admin-sidebar";

export type AdminShellProps = {
  header?: Omit<AdminHeaderProps, "children"> & { right?: ReactNode };
  sidebar: AdminSidebarProps;
  children: ReactNode;
  className?: string;
};

export function AdminShell({ header, sidebar, children, className }: AdminShellProps) {
  const { right, ...headerRest } = header ?? {};
  return (
    <div
      className={cn(
        "flex h-dvh min-h-0 max-h-dvh flex-col overflow-hidden bg-[var(--el-bg-page)]",
        className,
      )}
    >
      <AdminHeader {...headerRest}>{right}</AdminHeader>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <AdminSidebar {...sidebar} />
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden thin-scrollbar">
          <main>{children}</main>
        </div>
      </div>
    </div>
  );
}
