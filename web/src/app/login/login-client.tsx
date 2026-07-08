"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LoginCard } from "@/components/login/login-card";
import { LoginForm } from "@/components/login/login-form";
import { apiClient, ApiError } from "@/lib/api";
import { persistAuthSession, readAuthSession, type AuthUser } from "@/lib/auth";

const TASK_BOARD_PATH = "/chat/messages";

type LoginResponse = {
  access_token: string;
  user: AuthUser;
};

export function LoginClient() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (readAuthSession()) {
      router.replace(TASK_BOARD_PATH);
    }
  }, [router]);

  async function handleLogin(values: { username: string; password: string }) {
    setError(null);
    try {
      const { data } = await apiClient.post<LoginResponse>("/auth/login", {
        username: values.username,
        password: values.password,
      });
      persistAuthSession({
        access_token: data.access_token,
        user: data.user,
      });
      router.replace(TASK_BOARD_PATH);
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "登录失败，请稍后重试。";
      setError(message);
    }
  }

  return (
    <LoginCard title="智能体任务调度平台" description="请使用账号密码登录">
      {error && (
        <div
          className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}
      <LoginForm onSubmit={handleLogin} />
    </LoginCard>
  );
}
