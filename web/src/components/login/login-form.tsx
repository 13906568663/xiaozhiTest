"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export type LoginFormValues = {
  username: string;
  password: string;
};

export type LoginFormProps = {
  onSubmit: (values: LoginFormValues) => void | Promise<void>;
  className?: string;
  submitLabel?: string;
};

export function LoginForm({ onSubmit, className, submitLabel = "登录" }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<{ username?: string; password?: string }>({});

  const validate = () => {
    const next: { username?: string; password?: string } = {};
    if (!username.trim()) next.username = "请输入用户名";
    if (!password) next.password = "请输入密码";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!validate()) return;
      setPending(true);
      try {
        await onSubmit({ username, password });
      } finally {
        setPending(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onSubmit, username, password],
  );

  return (
    <form className={cn("flex flex-col gap-5", className)} onSubmit={handleSubmit} noValidate>
      <div className="space-y-1">
        <Label htmlFor="web-login-username">账号</Label>
        <Input
          id="web-login-username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(ev) => { setErrors((e) => ({ ...e, username: undefined })); setUsername(ev.target.value); }}
          placeholder="请输入用户名或邮箱"
        />
        <FieldError message={errors.username} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="web-login-password">密码</Label>
        <Input
          id="web-login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(ev) => { setErrors((e) => ({ ...e, password: undefined })); setPassword(ev.target.value); }}
          placeholder="请输入密码"
        />
        <FieldError message={errors.password} />
      </div>
      <Button type="submit" className="mt-1 w-full" disabled={pending}>
        {pending ? "提交中…" : submitLabel}
      </Button>
    </form>
  );
}
