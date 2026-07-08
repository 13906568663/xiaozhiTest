"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { MultiSelect, type MultiSelectOption } from "@/components/ui/multi-select";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { useFormErrors } from "@/hooks/use-form-errors";

type RoleBrief = { id: string; name: string; code: string };

export default function UserCreatePage() {
  const router = useRouter();
  const [form, setForm] = useState({
    username: "",
    display_name: "",
    password: "",
    phone: "",
    role_ids: [] as string[],
    department: "",
    status: "active",
  });
  const [roles, setRoles] = useState<MultiSelectOption[]>([]);
  const [saving, setSaving] = useState(false);
  const { errors, setErrors, clearErrors } = useFormErrors();

  const set = (key: string, val: unknown) => {
    clearErrors(key);
    setForm((f) => ({ ...f, [key]: val }));
  };

  const loadRoles = useCallback(async () => {
    try {
      const { data } = await apiClient.get<RoleBrief[]>("/roles");
      setRoles(
        (Array.isArray(data) ? data : []).map((r) => ({
          value: r.id,
          label: r.name,
        })),
      );
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadRoles();
  }, [loadRoles]);

  const handleSave = async () => {
    const next: Record<string, string> = {};
    if (!form.username.trim()) next.username = "请输入用户名";
    if (!form.display_name.trim()) next.display_name = "请输入姓名";
    if (!form.password) next.password = "请输入初始密码";
    else if (form.password.length < 8) next.password = "密码长度至少 8 位";
    if (form.phone.trim() && !/^1[3-9]\d{9}$/.test(form.phone.trim())) {
      next.phone = "请输入正确的手机号码（11位）";
    }
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }

    setSaving(true);
    try {
      await apiClient.post("/users", {
        username: form.username.trim(),
        display_name: form.display_name.trim(),
        password: form.password,
        phone: form.phone.trim() || undefined,
        role_ids: form.role_ids,
        department: form.department.trim() || undefined,
        status: form.status,
      });
      toast.success("新增成功");
      router.push("/iam/users");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="新增用户"
        breadcrumb={[
          { label: "用户中心" },
          { label: "用户管理", href: "/iam/users" },
          { label: "新增" },
        ]}
      />

      <div className="flex flex-col gap-5 rounded border border-[#EBEEF5] bg-white px-6 py-5">
        <FormField label="用户名" required layout="horizontal" error={errors.username}>
          <Input
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
            placeholder="请输入用户名"
          />
        </FormField>

        <FormField label="姓名" required layout="horizontal" error={errors.display_name}>
          <Input
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            placeholder="请输入姓名"
          />
        </FormField>

        <FormField label="初始密码" required layout="horizontal" error={errors.password}>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            placeholder="请输入初始密码（至少 8 位）"
          />
        </FormField>

        <FormField label="手机号码" layout="horizontal" error={errors.phone}>
          <Input
            value={form.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="请输入手机号码"
          />
        </FormField>

        <FormField label="角色" layout="horizontal">
          <MultiSelect
            value={form.role_ids}
            onChange={(v) => set("role_ids", v)}
            options={roles}
            placeholder="请选择角色"
          />
        </FormField>

        <FormField label="部门" layout="horizontal">
          <Input
            value={form.department}
            onChange={(e) => set("department", e.target.value)}
            placeholder="请输入部门"
          />
        </FormField>

        <FormField label="状态" layout="horizontal">
          <Select
            className="w-[200px]"
            value={form.status}
            onChange={(e) => set("status", e.target.value)}
            options={[
              { value: "active", label: "正常" },
              { value: "disabled", label: "禁用" },
            ]}
            placeholder="请选择"
          />
        </FormField>

        <div className="flex items-center justify-end gap-3 border-t border-transparent pt-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push("/iam/users")}
          >
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            {saving ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
    </div>
  );
}
