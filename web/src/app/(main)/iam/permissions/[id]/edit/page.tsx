"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { useFormErrors } from "@/hooks/use-form-errors";

type PermissionDetail = {
  id: string;
  code: string;
  resource: string;
  action: string;
  description: string | null;
};

type MenuOption = { value: string; label: string };

export default function PermissionEditPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [loading, setLoading] = useState(true);
  const [menuOptions, setMenuOptions] = useState<MenuOption[]>([]);
  const [form, setForm] = useState({
    name: "",
    code: "",
    type: "",
    resource: "",
    description: "",
  });
  const [saving, setSaving] = useState(false);
  const { errors, setErrors, clearErrors } = useFormErrors();

  const set = (key: string, val: string) => {
    clearErrors(key);
    setForm((f) => ({ ...f, [key]: val }));
  };

  const validate = () => {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "请输入权限名称";
    if (!form.code.trim()) next.code = "请输入权限标识";
    else if (!/^[\w:]+$/.test(form.code.trim())) next.code = "权限标识只能包含字母、数字、下划线和冒号";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [permRes, allRes] = await Promise.all([
        apiClient.get<PermissionDetail>(`/permissions/${params.id}`),
        apiClient.get<{ resource: string }[]>("/permissions"),
      ]);
      const p = permRes.data;
      setForm({
        name: p.description || p.code,
        code: p.code,
        type: "",
        resource: p.resource,
        description: p.description || "",
      });
      const resources = [
        ...new Set(
          (Array.isArray(allRes.data) ? allRes.data : []).map(
            (x) => (x as PermissionDetail).resource,
          ),
        ),
      ].sort();
      setMenuOptions(resources.map((r) => ({ value: r, label: r })));
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
    const parts = form.code.trim().split(":");
    setSaving(true);
    try {
      await apiClient.put(`/permissions/${params.id}`, {
        code: form.code.trim(),
        resource: form.resource || (parts.length > 1 ? parts[0] : form.name.trim()),
        action: parts.length > 1 ? parts.slice(1).join(":") : form.code.trim(),
        description: form.description.trim() || form.name.trim(),
      });
      toast.success("保存成功");
      router.push("/iam/permissions");
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
        title="编辑权限"
        breadcrumb={[
          { label: "用户中心" },
          { label: "权限管理", href: "/iam/permissions" },
          { label: "编辑" },
        ]}
      />

      <div className="flex flex-col gap-5 rounded border border-[#EBEEF5] bg-white px-6 py-5">
        <FormField label="权限名称" required layout="horizontal" error={errors.name}>
          <Input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="请输入权限名称"
          />
        </FormField>

        <FormField label="权限标识" required layout="horizontal" error={errors.code}>
          <Input
            value={form.code}
            onChange={(e) => set("code", e.target.value)}
            placeholder="如 task:read"
          />
        </FormField>

        <FormField label="类型" layout="horizontal">
          <Select
            className="w-[200px]"
            value={form.type}
            onChange={(e) => set("type", e.target.value)}
            options={[
              { value: "menu", label: "菜单" },
              { value: "button", label: "按钮" },
              { value: "api", label: "接口" },
            ]}
            placeholder="请选择"
          />
        </FormField>

        <FormField label="所属菜单" layout="horizontal">
          <Select
            value={form.resource}
            onChange={(e) => set("resource", e.target.value)}
            options={menuOptions}
            placeholder="请选择所属菜单"
          />
        </FormField>

        <FormField label="说明" layout="horizontal">
          <Textarea
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            placeholder="请输入说明"
            className="min-h-[100px]"
          />
        </FormField>

        <div className="flex items-center justify-end gap-3 border-t border-transparent pt-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push("/iam/permissions")}
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
