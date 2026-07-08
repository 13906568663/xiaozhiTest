"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { useFormErrors } from "@/hooks/use-form-errors";

type PermissionRead = {
  id: string;
  code: string;
  resource: string;
  action: string;
  description: string | null;
};

export default function RoleCreatePage() {
  const router = useRouter();
  const [formName, setFormName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [allPermissions, setAllPermissions] = useState<PermissionRead[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [permLoading, setPermLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { errors, setErrors, clearErrors } = useFormErrors();

  const loadPermissions = useCallback(async () => {
    setPermLoading(true);
    try {
      const { data } = await apiClient.get<PermissionRead[]>("/permissions");
      setAllPermissions(Array.isArray(data) ? data : []);
    } catch {
      /* ignore */
    } finally {
      setPermLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPermissions();
  }, [loadPermissions]);

  const permsByResource = (() => {
    const m = new Map<string, PermissionRead[]>();
    for (const p of allPermissions) {
      const list = m.get(p.resource) ?? [];
      list.push(p);
      m.set(p.resource, list);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], "zh-CN"));
  })();

  const togglePerm = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const toggleResource = (resource: string, checked: boolean) => {
    const ids = allPermissions
      .filter((p) => p.resource === resource)
      .map((p) => p.id);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  const handleSave = async () => {
    const next: Record<string, string> = {};
    if (!formName.trim()) next.name = "请输入角色名称";
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }

    setSaving(true);
    try {
      await apiClient.post("/roles", {
        name: formName.trim(),
        code: formName.trim().toLowerCase().replace(/\s+/g, "_"),
        description: formDescription.trim() || null,
        permission_ids: [...selectedIds],
      });
      toast.success("新增成功");
      router.push("/iam/roles");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="新增角色"
        breadcrumb={[
          { label: "用户中心" },
          { label: "角色管理", href: "/iam/roles" },
          { label: "新增" },
        ]}
      />

      <div className="flex flex-col gap-5 rounded border border-[#EBEEF5] bg-white px-6 py-5">
        <FormField
          label="角色名称"
          required
          layout="horizontal"
          error={errors.name}
        >
          <Input
            value={formName}
            onChange={(e) => {
              clearErrors("name");
              setFormName(e.target.value);
            }}
            placeholder="请输入角色名称"
          />
        </FormField>

        <FormField label="说明" layout="horizontal">
          <Textarea
            value={formDescription}
            onChange={(e) => setFormDescription(e.target.value)}
            placeholder="请输入角色说明"
            className="min-h-[100px]"
          />
        </FormField>

        <FormField label="权限配置" layout="horizontal">
          <div className="rounded border border-[var(--el-border-base)] p-3">
            {permLoading ? (
              <p className="text-sm text-[var(--el-text-placeholder)]">
                加载权限中…
              </p>
            ) : permsByResource.length === 0 ? (
              <p className="text-sm text-[var(--el-text-placeholder)]">
                暂无权限数据
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {permsByResource.map(([resource, perms]) => {
                  const ids = perms.map((p) => p.id);
                  const selectedCount = ids.filter((id) =>
                    selectedIds.has(id),
                  ).length;
                  const allChecked = selectedCount === ids.length;
                  const indeterminate =
                    selectedCount > 0 && selectedCount < ids.length;
                  return (
                    <div key={resource}>
                      <Checkbox
                        checked={allChecked}
                        indeterminate={indeterminate}
                        onChange={(e) =>
                          toggleResource(resource, e.target.checked)
                        }
                        label={
                          <span className="text-[13px] font-normal text-[var(--el-text-primary)]">
                            {resource}
                          </span>
                        }
                      />
                      <div className="flex flex-col gap-2 pl-6 pt-1">
                        {perms.map((p) => (
                          <Checkbox
                            key={p.id}
                            checked={selectedIds.has(p.id)}
                            onChange={(e) =>
                              togglePerm(p.id, e.target.checked)
                            }
                            label={
                              <span className="text-xs text-[var(--el-text-regular)]">
                                {p.description || p.code}
                              </span>
                            }
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </FormField>

        <div className="flex items-center justify-end gap-3 border-t border-transparent pt-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push("/iam/roles")}
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
