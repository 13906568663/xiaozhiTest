"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ActionButtons } from "@/components/ui/action-buttons";
import { PageHeader } from "@/components/ui/page-header";
import { DataTable, type Column } from "@/components/ui/data-table";
import { FilterBar } from "@/components/ui/filter-bar";
import { Pagination } from "@/components/ui/pagination";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, type SelectOption } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { MethodTag } from "@/components/ui/method-tag";
import { toast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type DynamicToolRow = {
  id: string;
  name: string;
  description: string | null;
  method: string;
  url: string;
  headers: Record<string, unknown>;
  parameters_schema: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
};

type ToolsetListResponse = {
  items: DynamicToolRow[];
  total: number;
};

type FormState = {
  name: string;
  description: string;
  method: string;
  url: string;
  timeout: string;
  headersStr: string;
  paramsStr: string;
  schemaStr: string;
  status: string;
};

const METHOD_OPTIONS: SelectOption[] = [
  { value: "GET", label: "GET" },
  { value: "POST", label: "POST" },
  { value: "PUT", label: "PUT" },
  { value: "DELETE", label: "DELETE" },
  { value: "PATCH", label: "PATCH" },
];

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    method: "POST",
    url: "",
    timeout: "30",
    headersStr: "",
    paramsStr: "",
    schemaStr: "",
    status: "active",
  };
}

function stringifyJsonField(obj: Record<string, unknown> | null | undefined): string {
  if (!obj || typeof obj !== "object" || Object.keys(obj).length === 0) return "";
  return JSON.stringify(obj, null, 2);
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("zh-CN");
  } catch {
    return "—";
  }
}

function parseOptionalJsonObject(
  raw: string,
  fieldLabel: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const t = raw.trim();
  if (!t) return { ok: true, value: {} };
  try {
    const v = JSON.parse(t) as unknown;
    if (v === null || typeof v !== "object" || Array.isArray(v)) {
      return { ok: false, error: `${fieldLabel}须为 JSON 对象` };
    }
    return { ok: true, value: v as Record<string, unknown> };
  } catch {
    return { ok: false, error: `${fieldLabel} JSON 格式无效` };
  }
}

function ToolFormView({
  editingId,
  initialForm,
  onCancel,
  onSaved,
}: {
  editingId: string | null;
  initialForm: FormState;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const clearFormError = (...keys: string[]) => {
    setFormErrors((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const key of keys) {
        if (key in next) {
          delete next[key];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  };

  const handleSubmit = async () => {
    const errors: Record<string, string> = {};
    if (!form.name.trim()) errors.name = "请输入工具名";
    if (!form.method.trim()) errors.method = "请选择 Method";
    if (!form.url.trim()) errors.url = "请输入 URL";

    const headersParsed = parseOptionalJsonObject(form.headersStr, "请求头");
    if (!headersParsed.ok) errors.headersStr = headersParsed.error;

    const schemaParsed = parseOptionalJsonObject(form.schemaStr, "入参格式");
    if (!schemaParsed.ok) errors.schemaStr = schemaParsed.error;

    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      method: form.method,
      url: form.url.trim(),
      timeout: Number(form.timeout) || 30,
      headers: headersParsed.ok ? headersParsed.value : {},
      parameters_schema: schemaParsed.ok ? schemaParsed.value : {},
      status: form.status,
    };

    setSubmitting(true);
    try {
      if (editingId) {
        await apiClient.put(`/toolsets/${editingId}`, payload);
      } else {
        await apiClient.post("/toolsets", payload);
      }
      toast.success(editingId ? "保存成功" : "新建成功");
      onSaved();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "保存失败";
      setFormErrors({ _submit: msg });
    } finally {
      setSubmitting(false);
    }
  };

  const isEdit = !!editingId;

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title={isEdit ? "编辑接口" : "新建接口"}
        description="配置 HTTP 接口工具的详细信息"
        breadcrumb={[
          { label: "能力中心" },
          { label: "动态工具集" },
          { label: isEdit ? "编辑接口" : "新建接口" },
        ]}
        actions={
          <>
            <button
              type="button"
              className="rounded border border-[#DCDFE6] px-5 py-2 text-[13px] text-[#606266] transition-colors hover:border-[#C0C4CC] disabled:opacity-50"
              disabled={submitting}
              onClick={onCancel}
            >
              取消
            </button>
            <button
              type="button"
              className="rounded bg-[#409EFF] px-5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#66b1ff] disabled:opacity-50"
              disabled={submitting}
              onClick={() => void handleSubmit()}
            >
              {submitting ? "保存中…" : "保存"}
            </button>
          </>
        }
      />

      <div className="flex flex-col gap-[18px] rounded-md border border-[#EBEEF5] bg-white px-6 py-5">
        {formErrors._submit && (
          <div className="rounded-md border border-[var(--el-danger-light-5)] bg-[var(--el-danger-light-9)] px-3 py-2 text-sm text-[var(--el-danger)]">
            {formErrors._submit}
          </div>
        )}

        <div className="flex gap-4">
          <FormField label="工具名" required error={formErrors.name} className="flex-1">
            <Input
              value={form.name}
              onChange={(e) => {
                clearFormError("name", "_submit");
                setForm((f) => ({ ...f, name: e.target.value }));
              }}
              placeholder="create_ticket"
              maxLength={128}
            />
          </FormField>
          <FormField label="工具描述" className="flex-1">
            <Input
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="创建工单"
            />
          </FormField>
          <FormField label="Method" error={formErrors.method} className="w-[120px] shrink-0">
            <Select
              options={METHOD_OPTIONS}
              value={form.method}
              onChange={(e) => {
                clearFormError("method", "_submit");
                setForm((f) => ({ ...f, method: e.target.value }));
              }}
            />
          </FormField>
        </div>

        <FormField label="URL" required error={formErrors.url}>
          <Input
            value={form.url}
            onChange={(e) => {
              clearFormError("url", "_submit");
              setForm((f) => ({ ...f, url: e.target.value }));
            }}
            placeholder="https://api.example.com/tickets"
          />
        </FormField>

        <FormField label="超时秒数">
          <Input
            type="number"
            value={form.timeout}
            onChange={(e) => setForm((f) => ({ ...f, timeout: e.target.value }))}
            placeholder="30"
            min={1}
          />
        </FormField>

        <div className="flex gap-4">
          <FormField label="请求头" error={formErrors.headersStr} hint="覆盖全局" className="flex-1">
            <Textarea
              value={form.headersStr}
              onChange={(e) => {
                clearFormError("headersStr", "_submit");
                setForm((f) => ({ ...f, headersStr: e.target.value }));
              }}
              placeholder="X-Priority=high"
              className="h-16 font-mono text-xs"
            />
          </FormField>
          <FormField label="入参" hint="覆盖全局" className="flex-1">
            <Textarea
              value={form.paramsStr}
              onChange={(e) => setForm((f) => ({ ...f, paramsStr: e.target.value }))}
              placeholder="source=agent"
              className="h-16 font-mono text-xs"
            />
          </FormField>
        </div>

        <FormField label="入参格式" error={formErrors.schemaStr} hint="JSON Schema 定义 LLM 输入参数">
          <Textarea
            value={form.schemaStr}
            onChange={(e) => {
              clearFormError("schemaStr", "_submit");
              setForm((f) => ({ ...f, schemaStr: e.target.value }));
            }}
            placeholder='{ type: object, properties: { title: { type: string } }, required: [title] }'
            className="h-[100px] bg-[#FAFAFA] font-mono text-xs leading-relaxed"
          />
        </FormField>
      </div>
    </div>
  );
}

export default function CapabilitiesToolsetsPage() {
  const [view, setView] = useState<"list" | "form">("list");
  const [items, setItems] = useState<DynamicToolRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [nameFilter, setNameFilter] = useState("");
  const [nameDraft, setNameDraft] = useState("");
  const [refreshSeq, setRefreshSeq] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingForm, setEditingForm] = useState<FormState>(emptyForm);

  const [statusUpdatingId, setStatusUpdatingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const doSearch = useCallback(() => {
    setNameFilter(nameDraft.trim());
    setPage(1);
    setRefreshSeq((s) => s + 1);
  }, [nameDraft]);

  const doReset = useCallback(() => {
    setNameDraft("");
    setNameFilter("");
    setPage(1);
    setRefreshSeq((s) => s + 1);
  }, []);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const params: Record<string, string | number> = {
        page,
        page_size: pageSize,
      };
      const q = nameFilter.trim();
      if (q) params.name = q;

      const { data } = await apiClient.get<ToolsetListResponse>("/toolsets", { params });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "加载失败";
      setListError(msg);
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, nameFilter, refreshSeq]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  const openCreate = useCallback(() => {
    setEditingId(null);
    setEditingForm(emptyForm());
    setView("form");
  }, []);

  const openEdit = useCallback((row: DynamicToolRow) => {
    setEditingId(row.id);
    setEditingForm({
      name: row.name,
      description: row.description ?? "",
      method: row.method.toUpperCase(),
      url: row.url,
      timeout: "30",
      headersStr: stringifyJsonField(row.headers),
      paramsStr: "",
      schemaStr: stringifyJsonField(row.parameters_schema),
      status: row.status,
    });
    setView("form");
  }, []);

  const backToList = useCallback(() => {
    setView("list");
    setEditingId(null);
  }, []);

  const handleSaved = useCallback(() => {
    setView("list");
    setEditingId(null);
    void fetchList();
  }, [fetchList]);

  const handleToggleStatus = useCallback(
    async (row: DynamicToolRow, nextActive: boolean) => {
      const newStatus = nextActive ? "active" : "inactive";
      setStatusUpdatingId(row.id);
      try {
        await apiClient.put(`/toolsets/${row.id}`, { status: newStatus });
        await fetchList();
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "更新状态失败";
        setListError(msg);
      } finally {
        setStatusUpdatingId(null);
      }
    },
    [fetchList],
  );

  const handleConfirmDelete = useCallback(async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/toolsets/${confirmTarget.id}`);
      toast.success("操作成功");
      if (items.length === 1 && page > 1) setPage((p) => p - 1);
      else await fetchList();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "删除失败";
      toast.error(msg);
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  }, [confirmTarget, fetchList, items.length, page]);

  const columns: Column<DynamicToolRow>[] = useMemo(
    () => [
      {
        key: "name",
        title: "工具名",
        width: 180,
        ellipsis: true,
        render: (_, record) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-semibold text-[var(--el-text-primary)]">{record.name}</span>
            {record.description ? (
              <span className="line-clamp-2 text-xs text-[var(--el-text-secondary)]">
                {record.description}
              </span>
            ) : (
              <span className="text-xs text-[var(--el-text-placeholder)]">—</span>
            )}
          </div>
        ),
      },
      {
        key: "method",
        title: "Method",
        width: 80,
        align: "center",
        render: (_, record) => <MethodTag method={record.method} />,
      },
      {
        key: "url",
        title: "URL",
        render: (_, record) => (
          <span className="break-all font-mono text-xs text-[var(--el-text-secondary)]">{record.url}</span>
        ),
      },
      {
        key: "status",
        title: "状态",
        width: 72,
        align: "center",
        render: (_, record) => (
          <div className="flex justify-center">
            <ToggleSwitch
              checked={record.status === "active"}
              disabled={statusUpdatingId === record.id}
              onChange={(checked) => void handleToggleStatus(record, checked)}
            />
          </div>
        ),
      },
      {
        key: "updated_at",
        title: "更新时间",
        width: 140,
        align: "center",
        render: (v) => <span>{formatDate(String(v ?? ""))}</span>,
      },
      {
        key: "created_by",
        title: "创建人",
        width: 80,
        render: (v) => <span>{v ? String(v) : "—"}</span>,
      },
      {
        key: "created_at",
        title: "创建时间",
        width: 140,
        align: "center",
        render: (v) => <span>{formatDate(String(v ?? ""))}</span>,
      },
      {
        key: "id",
        title: "操作",
        width: 120,
        render: (_, record) => (
          <ActionButtons
            items={[
              { key: "edit", label: "编辑", onClick: () => openEdit(record) },
              {
                key: "delete",
                label: "删除",
                color: "danger",
                disabled: deletingId === record.id,
                onClick: () => setConfirmTarget({ id: record.id, name: record.name }),
              },
            ]}
          />
        ),
      },
    ],
    [statusUpdatingId, deletingId, openEdit, handleToggleStatus],
  );

  if (view === "form") {
    return (
      <ToolFormView
        editingId={editingId}
        initialForm={editingForm}
        onCancel={backToList}
        onSaved={handleSaved}
      />
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="动态工具集"
        description="集中配置 HTTP 接口工具，可被 MCP 或智能体挂载使用"
        breadcrumb={[{ label: "工具能力中心" }, { label: "动态工具集" }]}
      />

      <div className={cn("flex flex-col gap-3.5 rounded-md border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3", loading && "opacity-70")}>
        <FilterBar
          fields={[
            {
              key: "name",
              label: "工具名搜索",
              render: () => (
                <Input
                  className="h-8 border-[#DCDCDC]"
                  placeholder="请输入工具名"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") doSearch();
                  }}
                />
              ),
            },
          ]}
          onSearch={doSearch}
          onReset={doReset}
          extra={
            <Button variant="success" size="sm" onClick={openCreate}>
              新增工具
            </Button>
          }
        />

        {listError && (
          <div className="rounded-md border border-[var(--el-danger-light-5)] bg-[var(--el-danger-light-9)] px-3 py-2 text-sm text-[var(--el-danger)]">
            {listError}
          </div>
        )}

        <DataTable<DynamicToolRow>
          columns={columns}
          data={items}
          rowKey="id"
          emptyText={loading ? "加载中…" : "暂无数据"}
          headerClassName="bg-[#FAFAFA]"
        />
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          onChange={setPage}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setPage(1);
          }}
        />
      </div>

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认删除"
        message={`确定删除「${confirmTarget?.name}」？此操作不可撤销。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
