"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

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

type UserDetail = {
  id: string;
  username: string;
  display_name: string;
  phone?: string;
  department?: string;
  status: string;
  roles: { id: string; name: string }[];
};

export default function UserEditPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [loading, setLoading] = useState(true);
  const [roleOptions, setRoleOptions] = useState<MultiSelectOption[]>([]);
  const [form, setForm] = useState({
    username: "",
    display_name: "",
    phone: "",
    role_ids: [] as string[],
    department: "",
    status: "active",
  });
  const [saving, setSaving] = useState(false);
  const { errors, setErrors, clearErrors } = useFormErrors();

  const set = (key: string, val: unknown) => {
    clearErrors(key);
    setForm((f) => ({ ...f, [key]: val }));
  };

  const validate = () => {
    const next: Record<string, string> = {};
    if (!form.display_name.trim()) next.display_name = "请输入姓名";
    if (form.phone.trim() && !/^1[3-9]\d{9}$/.test(form.phone.trim())) {
      next.phone = "请输入正确的手机号码（11位）";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [userRes, rolesRes] = await Promise.all([
        apiClient.get<UserDetail>(`/users/${params.id}`),
        apiClient.get<RoleBrief[]>("/roles"),
      ]);
      const u = userRes.data;
      setForm({
        username: u.username,
        display_name: u.display_name || "",
        phone: u.phone || "",
        role_ids: (u.roles || []).map((r) => r.id),
        department: u.department || "",
        status: u.status,
      });
      setRoleOptions(
        (Array.isArray(rolesRes.data) ? rolesRes.data : []).map((r) => ({
          value: r.id,
          label: r.name,
        })),
      );
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      await apiClient.put(`/users/${params.id}`, {
        display_name: form.display_name.trim(),
        // 后端约定：传空串清除字段、传非空串覆盖、不传/undefined 不修改
        phone: form.phone.trim(),
        role_ids: form.role_ids,
        department: form.department.trim(),
        status: form.status,
      });
      toast.success("保存成功");
      router.push("/iam/users");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-sm text-[var(--el-text-placeholder)]">
        加载中…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="编辑用户"
        breadcrumb={[
          { label: "用户中心" },
          { label: "用户管理", href: "/iam/users" },
          { label: "编辑" },
        ]}
      />

      <div className="flex flex-col gap-5 rounded border border-[#EBEEF5] bg-white px-6 py-5">
        <FormField label="用户名" layout="horizontal">
          <Input value={form.username} disabled />
        </FormField>

        <FormField label="姓名" required layout="horizontal" error={errors.display_name}>
          <Input
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            placeholder="请输入姓名"
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
            options={roleOptions}
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
