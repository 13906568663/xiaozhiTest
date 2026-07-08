"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { LogOut, User, KeyRound } from "lucide-react";

import { AdminShell } from "@/components/admin/admin-shell";
import { Avatar } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownItem,
  DropdownDivider,
} from "@/components/ui/dropdown-menu";
import { ToastContainer } from "@/components/ui/toast";
import { defaultAdminNavSections } from "@/lib/admin-default-nav";
import { readAuthSession, clearAuthSession, type AuthSession } from "@/lib/auth";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);

  useEffect(() => {
    setSession(readAuthSession());
  }, []);

  useEffect(() => {
    if (session === null) {
      router.replace("/login");
    }
  }, [session, router]);

  const handleLogout = useCallback(() => {
    clearAuthSession();
    router.replace("/login");
  }, [router]);

  const navSections = defaultAdminNavSections;

  if (session === undefined || session === null) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[var(--el-fill-blank)] text-sm text-[var(--el-text-secondary)]">
        加载中…
      </div>
    );
  }

  const userLabel = session.user.display_name || session.user.username;

  return (
    <AdminShell
      sidebar={{ sections: navSections, activePath: pathname }}
      header={{
        right: (
          <>
            <span className="text-[var(--el-text-regular)]">手册</span>
            <DropdownMenu
              trigger={
                <div className="flex items-center gap-2">
                  <Avatar name={userLabel} size={28} />
                  <span className="text-sm text-[var(--el-text-regular)]">{userLabel}</span>
                </div>
              }
            >
              <div className="px-4 py-3">
                <p className="text-sm font-semibold text-[var(--el-text-primary)]">{userLabel}</p>
                <p className="mt-0.5 text-xs text-[var(--el-text-secondary)]">
                  {session.user.username}
                </p>
              </div>
              <DropdownDivider />
              <DropdownItem
                icon={<User className="size-4" />}
                onClick={() => router.push("/profile")}
              >
                个人资料
              </DropdownItem>
              <DropdownItem
                icon={<KeyRound className="size-4" />}
                onClick={() => router.push("/profile")}
              >
                修改密码
              </DropdownItem>
              <DropdownDivider />
              <DropdownItem
                icon={<LogOut className="size-4" />}
                onClick={handleLogout}
                danger
              >
                退出登录
              </DropdownItem>
            </DropdownMenu>
          </>
        ),
      }}
    >
      {children}
      <ToastContainer />
    </AdminShell>
  );
}
