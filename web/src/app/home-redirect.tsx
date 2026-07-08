"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { readAuthSession } from "@/lib/auth";

export function HomeRedirect() {
  const router = useRouter();

  useEffect(() => {
    if (readAuthSession()) {
      router.replace("/chat/messages");
    } else {
      router.replace("/login");
    }
  }, [router]);

  return (
    <div className="flex min-h-dvh items-center justify-center text-sm text-[var(--el-text-secondary)]">
      跳转中…
    </div>
  );
}
