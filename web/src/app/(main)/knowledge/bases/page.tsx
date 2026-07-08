"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Blocks, List, Info, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type Column, DataTable } from "@/components/ui/data-table";
import { FilterBar, type FilterField } from "@/components/ui/filter-bar";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Select, type SelectOption } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { toast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useFormErrors } from "@/hooks/use-form-errors";

type KnowledgeBaseRow = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
  chunk_method: string;
  chunk_size: number;
  chunk_overlap: number;
  document_count: number;
  embedding_config?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  created_by?: string;
};

type FormState = {
  code: string;
  name: string;
  description: string;
  embedding_provider: string;
  embedding_model: string;
  /** 字符串草稿，避免受控 number 在删空时被 `|| 0` 写死为 0 */
  embedding_dimensions: string;
  /** 留空表示由服务端按 host 决定（如 DashScope 默认 10） */
  embedding_max_batch_size: string;
  chunk_method: string;
  chunk_size: string;
  chunk_overlap: string;
};

const STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: "", label: "全部" },
  { value: "active", label: "启用" },
  { value: "inactive", label: "禁用" },
];

type CapabilityRow = {
  id: string;
  type: string;
  code: string;
  name: string;
  config_json: Record<string, unknown>;
  status: string;
};

const CHUNK_METHOD_OPTIONS: SelectOption[] = [
  { value: "fixed", label: "固定字数" },
  { value: "semantic", label: "语义分块" },
];

function emptyForm(): FormState {
  return {
    code: "",
    name: "",
    description: "",
    embedding_provider: "",
    embedding_model: "",
    embedding_dimensions: "1536",
    embedding_max_batch_size: "",
    chunk_method: "fixed",
    chunk_size: "512",
    chunk_overlap: "64",
  };
}

function formatDate(d: string) {
  return new Date(d).toLocaleDateString("zh-CN");
}

function fallback(text: string | null | undefined): string {
  return text || "—";
}

function formToCreateBody(
  form: FormState,
  existingEmbeddingConfig?: Record<string, unknown> | null,
) {
  const pr = form.embedding_provider.trim();
  const embedding_config: Record<string, unknown> = {
    ...(existingEmbeddingConfig && typeof existingEmbeddingConfig === "object"
      ? { ...existingEmbeddingConfig }
      : {}),
  };
  if (pr) embedding_config.provider_ref = pr;
  else delete embedding_config.provider_ref;

  const mbsRaw = form.embedding_max_batch_size.trim();
  if (mbsRaw) {
    const n = Number.parseInt(mbsRaw, 10);
    if (Number.isFinite(n) && n >= 1 && n <= 512) {
      embedding_config.max_batch_size = n;
    }
  } else {
    delete embedding_config.max_batch_size;
  }

  return {
    code: form.code.trim(),
    name: form.name.trim(),
    description: form.description.trim() || null,
    status: "active",
    embedding_model: form.embedding_model.trim(),
    embedding_dimensions: Number(String(form.embedding_dimensions).trim()),
    embedding_config,
    chunk_method: form.chunk_method,
    chunk_size: Number(String(form.chunk_size).trim()),
    chunk_overlap: Number(String(form.chunk_overlap).trim()),
  };
}

/* ─── Section wrapper for the dialog ─── */
function FormSection({
  icon,
  tag,
  title,
  children,
}: {
  icon: React.ReactNode;
  tag: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-[#EBEEF5] bg-[#FAFAFA] p-4">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-md bg-[#ECF5FF]">
          {icon}
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-semibold tracking-widest text-[#C0C4CC]">{tag}</span>
          <span className="text-sm font-semibold text-[#303133]">{title}</span>
        </div>
      </div>
      {children}
    </div>
  );
}

export default function KnowledgeBasesPage() {
  const router = useRouter();
  const [allItems, setAllItems] = useState<KnowledgeBaseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState<CapabilityRow[]>([]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [nameDraft, setNameDraft] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [creatorDraft, setCreatorDraft] = useState("");
  const [creatorFilter, setCreatorFilter] = useState("");
  const [statusDraft, setStatusDraft] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [editingRow, setEditingRow] = useState<KnowledgeBaseRow | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const { errors: formErrors, setErrors: setFormErrors, clearErrors: clearFormErrors } = useFormErrors();
  const [saving, setSaving] = useState(false);

  const providerOptions = useMemo<SelectOption[]>(
    () => providers.map((p) => ({ value: p.code, label: p.name })),
    [providers],
  );

  const embeddingModelOptions = useMemo<SelectOption[]>(() => {
    const matched = providers.find((p) => p.code === form.embedding_provider);
    if (!matched) return [];
    const models = matched.config_json?.available_models;
    if (Array.isArray(models)) {
      return models.map((m: unknown) => {
        const obj = m as Record<string, unknown>;
        const name = String(obj.model_name ?? obj.name ?? obj.id ?? "");
        return { value: name, label: name };
      }).filter((o) => o.value);
    }
    const single = matched.config_json?.api_model;
    if (typeof single === "string" && single) {
      return [{ value: single, label: single }];
    }
    return [];
  }, [providers, form.embedding_provider]);

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await apiClient.get<CapabilityRow[]>("/capabilities", {
        params: { type: "model" },
      });
      const list = Array.isArray(data) ? data : [];
      setProviders(list.filter((c) => c.status === "active"));
    } catch {
      setProviders([]);
    }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<KnowledgeBaseRow[]>("/knowledge-bases");
      setAllItems(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载列表失败");
      setAllItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
    void loadProviders();
  }, [loadList, loadProviders]);

  const filtered = useMemo(() => {
    const qName = nameFilter.trim().toLowerCase();
    const qCreator = creatorFilter.trim().toLowerCase();
    return allItems.filter((row) => {
      if (qName && !row.name.toLowerCase().includes(qName)) return false;
      if (qCreator && !(row.created_by ?? "").toLowerCase().includes(qCreator)) return false;
      if (statusFilter && row.status !== statusFilter) return false;
      return true;
    });
  }, [allItems, nameFilter, creatorFilter, statusFilter]);

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const pageItems = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, page, pageSize]);

  const openCreate = () => {
    setDialogMode("create");
    setEditingRow(null);
    setForm(emptyForm());
    setFormErrors({});
    setDialogOpen(true);
  };

  const openEdit = (row: KnowledgeBaseRow) => {
    setDialogMode("edit");
    setEditingRow(row);
    const ec = row.embedding_config;
    const providerRef =
      typeof ec?.provider_ref === "string" && ec.provider_ref.trim()
        ? ec.provider_ref.trim()
        : "";
    const rawMbs = ec?.max_batch_size;
    const embeddingMaxBatch =
      typeof rawMbs === "number" && Number.isFinite(rawMbs)
        ? String(Math.trunc(rawMbs))
        : typeof rawMbs === "string" && rawMbs.trim()
          ? rawMbs.trim()
          : "";
    setForm({
      code: row.code,
      name: row.name,
      description: row.description ?? "",
      embedding_provider: providerRef,
      embedding_model: (row.embedding_model || "text-embedding-3-small").trim(),
      embedding_dimensions: String(row.embedding_dimensions ?? 1536),
      embedding_max_batch_size: embeddingMaxBatch,
      chunk_method: row.chunk_method || "fixed",
      chunk_size: String(row.chunk_size ?? 512),
      chunk_overlap: String(row.chunk_overlap ?? 64),
    });
    setFormErrors({});
    setDialogOpen(true);
  };

  const closeDialog = () => {
    if (saving) return;
    setDialogOpen(false);
  };

  const validateForm = (): boolean => {
    const next: Record<string, string> = {};
    if (!form.code.trim()) next.code = "请输入编码";
    else if (!/^[a-zA-Z0-9_-]+$/.test(form.code.trim()))
      next.code = "编码仅支持字母、数字、下划线和短横线";
    if (!form.name.trim()) next.name = "请输入名称";
    if (!form.embedding_provider.trim()) next.embedding_provider = "请选择 Provider";
    if (!form.embedding_model.trim()) next.embedding_model = "请选择 Embedding 模型";
    const dim = Number(form.embedding_dimensions.trim());
    if (!Number.isFinite(dim) || dim < 1) next.embedding_dimensions = "向量维度须为 ≥1 的数字";
    const mbs = form.embedding_max_batch_size.trim();
    if (mbs) {
      const n = Number.parseInt(mbs, 10);
      if (!Number.isFinite(n) || n < 1 || n > 512) {
        next.embedding_max_batch_size = "单次条数须为 1～512 的整数";
      }
    }
    const cs = Number(form.chunk_size.trim());
    if (!Number.isFinite(cs) || cs < 64) next.chunk_size = "分块大小须为 ≥64 的数字";
    const co = Number(form.chunk_overlap.trim());
    if (!Number.isFinite(co) || co < 0) next.chunk_overlap = "分块重叠须为 ≥0 的数字";
    else if (co >= cs) next.chunk_overlap = "重叠须小于分块大小";
    setFormErrors(next);
    return Object.keys(next).length === 0;
  };

  const submitForm = async () => {
    if (!validateForm()) return;
    setSaving(true);
    try {
      if (dialogMode === "create") {
        await apiClient.post("/knowledge-bases", formToCreateBody(form, null));
      } else if (editingRow) {
        await apiClient.put(`/knowledge-bases/${editingRow.id}`, {
          ...formToCreateBody(form, editingRow.embedding_config ?? null),
          status: editingRow.status,
        });
      }
      setDialogOpen(false);
      await loadList();
      toast.success("操作成功");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/knowledge-bases/${confirmTarget.id}`);
      toast.success("操作成功");
      await loadList();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  const handleToggleStatus = async (row: KnowledgeBaseRow, nextActive: boolean) => {
    const nextStatus = nextActive ? "active" : "inactive";
    if (row.status === nextStatus) return;
    setTogglingId(row.id);
    try {
      await apiClient.put(`/knowledge-bases/${row.id}`, {
        code: row.code,
        name: row.name,
        description: row.description ?? null,
        status: nextStatus,
        embedding_model: row.embedding_model,
        embedding_dimensions: row.embedding_dimensions,
        chunk_method: row.chunk_method,
        chunk_size: row.chunk_size,
        chunk_overlap: row.chunk_overlap,
        embedding_config: row.embedding_config ?? {},
      });
      await loadList();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "更新状态失败");
    } finally {
      setTogglingId(null);
    }
  };

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "name",
        label: "名称",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setNameFilter(nameDraft);
                setPage(1);
              }
            }}
          />
        ),
      },
      {
        key: "creator",
        label: "创建人",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            value={creatorDraft}
            onChange={(e) => setCreatorDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setCreatorFilter(creatorDraft);
                setPage(1);
              }
            }}
          />
        ),
      },
      {
        key: "status",
        label: "状态",
        render: () => (
          <Select
            className="h-8 border-[#DCDCDC]"
            value={statusDraft}
            options={STATUS_FILTER_OPTIONS}
            onChange={(e) => setStatusDraft(e.target.value)}
          />
        ),
      },
    ],
    [nameDraft, creatorDraft, statusDraft],
  );

  const columns: Column<KnowledgeBaseRow>[] = [
    {
      key: "name",
      title: "名称",
      width: 110,
      ellipsis: false,
      render: (_, row) => (
        <button
          type="button"
          className="text-left text-[13px] text-[#606266] hover:text-[#409EFF] hover:underline"
          onClick={() => router.push(`/knowledge/bases/${row.id}`)}
        >
          {row.name}
        </button>
      ),
    },
    {
      key: "description",
      title: "内容摘要",
      width: 300,
      ellipsis: true,
      render: (v) => fallback(typeof v === "string" ? v : null),
    },
    {
      key: "embedding_model",
      title: "说明",
      width: 200,
      ellipsis: true,
      render: (v) => (typeof v === "string" && v ? v : "—"),
    },
    {
      key: "created_by",
      title: "创建人",
      width: 110,
      align: "center",
      render: (v) => (typeof v === "string" && v ? v : "—"),
    },
    {
      key: "created_at",
      title: "创建时间",
      width: 110,
      align: "center",
      render: (v) => (typeof v === "string" ? formatDate(v) : "—"),
    },
    {
      key: "updated_at",
      title: "修改时间",
      width: 110,
      align: "center",
      render: (v) => (typeof v === "string" ? formatDate(v) : "—"),
    },
    {
      key: "status",
      title: "状态",
      align: "center",
      ellipsis: false,
      render: (_, row) => (
        <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
          <ToggleSwitch
            checked={row.status === "active"}
            disabled={togglingId === row.id}
            onChange={(checked) => void handleToggleStatus(row, checked)}
          />
        </div>
      ),
    },
    {
      key: "actions",
      title: "操作",
      width: 140,
      ellipsis: false,
      render: (_, row) => (
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="rounded border border-[#DCDFE6] px-3 py-1 text-xs text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
            onClick={() => openEdit(row)}
          >
            编辑
          </button>
          <button
            type="button"
            disabled={deletingId === row.id}
            className="rounded border border-[#FFCDD2] px-3 py-1 text-xs text-[#F56C6C] transition-colors hover:bg-[#FEF0F0] disabled:opacity-50"
            onClick={() => setConfirmTarget({ id: row.id, name: row.name })}
          >
            删除
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="知识库"
        description="管理向量知识库、文档上传与检索配置"
        breadcrumb={[{ label: "知识管理中心" }, { label: "知识库管理" }]}
      />

      <div
        className={cn(
          "flex flex-col gap-3.5 rounded border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3",
          loading && "opacity-70",
        )}
      >
        <FilterBar
          fields={filterFields}
          onSearch={() => {
            setNameFilter(nameDraft);
            setCreatorFilter(creatorDraft);
            setStatusFilter(statusDraft);
            setPage(1);
          }}
          onReset={() => {
            setNameDraft("");
            setNameFilter("");
            setCreatorDraft("");
            setCreatorFilter("");
            setStatusDraft("");
            setStatusFilter("");
            setPage(1);
          }}
          extra={
            <Button variant="success" size="sm" onClick={openCreate}>
              新增
            </Button>
          }
        />
        <DataTable<KnowledgeBaseRow>
          columns={columns}
          data={pageItems}
          rowKey="id"
          emptyText={loading ? "加载中…" : "暂无数据"}
          onRowClick={(row) => router.push(`/knowledge/bases/${row.id}`)}
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

      {/* ── Create / Edit Dialog ── */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/15" onClick={closeDialog} aria-hidden />
          <div
            className="relative z-10 flex max-h-[85vh] flex-col overflow-hidden rounded-lg border border-[#E4E7ED] bg-white shadow-2xl"
            style={{ width: 860 }}
            role="dialog"
            aria-modal="true"
          >
            {/* Header */}
            <div className="border-b border-[#EBEEF5] px-5 py-[18px]">
              <div className="flex items-center justify-between">
                <span className="rounded bg-[#ECF5FF] px-2.5 py-0.5 text-[11px] font-semibold text-[#409EFF]">
                  {dialogMode === "create" ? "Create" : "Edit"}
                </span>
                <button
                  type="button"
                  onClick={closeDialog}
                  className="flex items-center justify-center text-[#C0C4CC] hover:text-[#909399]"
                >
                  <X className="size-[18px]" />
                </button>
              </div>
              <h2 className="mt-1.5 text-xl font-bold text-[#303133]">
                {dialogMode === "create" ? "新建知识库" : "编辑知识库"}
              </h2>
              <p className="mt-1 text-xs text-[#909399]">
                把引用标识、向量模型和切块策略一次配好，创建后就可以立刻开始导入文档。
              </p>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 thin-scrollbar">
              <div className="flex flex-col gap-3">
                {/* Section 1: 基础信息 */}
                <FormSection
                  icon={<Sparkles className="size-[15px] text-[#409EFF]" />}
                  tag="IDENTITY"
                  title="基础信息"
                >
                  <div className="flex flex-col gap-2.5">
                    <div className="flex gap-3">
                      <FormField label="编码" required error={formErrors.code} className="flex-1">
                        <Input
                          className="h-[34px] text-xs"
                          value={form.code}
                          disabled={dialogMode === "edit"}
                          onChange={(e) => {
                            clearFormErrors("code");
                            setForm((f) => ({ ...f, code: e.target.value }));
                          }}
                          placeholder="如 sop-kb"
                        />
                      </FormField>
                      <FormField label="名称" required error={formErrors.name} className="flex-1">
                        <Input
                          className="h-[34px] text-xs"
                          value={form.name}
                          onChange={(e) => {
                            clearFormErrors("name");
                            setForm((f) => ({ ...f, name: e.target.value }));
                          }}
                          placeholder="如 标准作业知识库"
                        />
                      </FormField>
                    </div>
                    <FormField label="描述">
                      <Textarea
                        className="min-h-[64px] text-xs"
                        value={form.description}
                        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                        placeholder="请填写用途说明（可选）"
                      />
                    </FormField>
                  </div>
                </FormSection>

                {/* Section 2: 向量模型 */}
                <FormSection
                  icon={<Blocks className="size-[15px] text-[#409EFF]" />}
                  tag="EMBEDDING"
                  title="向量模型"
                >
                  <div className="flex flex-col gap-2.5">
                    <div className="flex gap-3">
                      <FormField
                        label="Provider"
                        required
                        error={formErrors.embedding_provider}
                        className="flex-1"
                      >
                        <Select
                          className="h-[34px] text-xs"
                          value={form.embedding_provider}
                          options={providerOptions}
                          placeholder="请选择 Provider"
                          onChange={(e) => {
                            clearFormErrors("embedding_provider", "embedding_model");
                            setForm((f) => ({
                              ...f,
                              embedding_provider: e.target.value,
                              embedding_model: "",
                            }));
                          }}
                        />
                      </FormField>
                      <FormField
                        label="Embedding 模型"
                        required
                        error={formErrors.embedding_model}
                        className="flex-1"
                      >
                        <Select
                          className="h-[34px] text-xs"
                          value={form.embedding_model}
                          options={embeddingModelOptions}
                          placeholder="请选择 Embedding 模型"
                          onChange={(e) => {
                            clearFormErrors("embedding_model");
                            setForm((f) => ({ ...f, embedding_model: e.target.value }));
                          }}
                        />
                      </FormField>
                      <FormField
                        label="向量维度"
                        error={formErrors.embedding_dimensions}
                        className="w-40"
                      >
                        <Input
                          type="number"
                          className="h-[34px] text-xs"
                          min={1}
                          value={form.embedding_dimensions}
                          onChange={(e) => {
                            clearFormErrors("embedding_dimensions");
                            setForm((f) => ({
                              ...f,
                              embedding_dimensions: e.target.value,
                            }));
                          }}
                        />
                      </FormField>
                      <FormField
                        label="单次 embedding 条数"
                        error={formErrors.embedding_max_batch_size}
                        className="w-36 shrink-0"
                      >
                        <Input
                          type="number"
                          className="h-[34px] text-xs"
                          min={1}
                          max={512}
                          value={form.embedding_max_batch_size}
                          onChange={(e) => {
                            clearFormErrors("embedding_max_batch_size");
                            setForm((f) => ({
                              ...f,
                              embedding_max_batch_size: e.target.value,
                            }));
                          }}
                          placeholder="自动"
                        />
                      </FormField>
                    </div>
                    <div className="flex items-center gap-1 text-[11px] text-[#909399]">
                      <Info className="size-3" />
                      <span>
                        模型列表来自全局「模型管理」，可在 设置 &gt; 模型管理 中添加。通义/DashScope
                        等单次最多 10 条时可留空（后端按域名自动限制）或在此填写 10。
                      </span>
                    </div>
                  </div>
                </FormSection>

                {/* Section 3: 切块策略 */}
                <FormSection
                  icon={<List className="size-4 text-[#409EFF]" />}
                  tag="CHUNKING"
                  title="切块策略"
                >
                  <div className="flex gap-3">
                    <FormField label="切割方式" className="flex-1">
                      <Select
                        className="h-[34px] text-xs"
                        value={form.chunk_method}
                        options={CHUNK_METHOD_OPTIONS}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, chunk_method: e.target.value }))
                        }
                      />
                    </FormField>
                    <FormField label="分块大小" error={formErrors.chunk_size} className="flex-1">
                      <Input
                        type="number"
                        className="h-[34px] text-xs"
                        min={64}
                        value={form.chunk_size}
                        onChange={(e) => {
                          clearFormErrors("chunk_size", "chunk_overlap");
                          setForm((f) => ({ ...f, chunk_size: e.target.value }));
                        }}
                      />
                    </FormField>
                    <FormField
                      label="分块重叠"
                      error={formErrors.chunk_overlap}
                      className="flex-1"
                    >
                      <Input
                        type="number"
                        className="h-[34px] text-xs"
                        min={0}
                        value={form.chunk_overlap}
                        onChange={(e) => {
                          clearFormErrors("chunk_overlap");
                          setForm((f) => ({ ...f, chunk_overlap: e.target.value }));
                        }}
                      />
                    </FormField>
                  </div>
                </FormSection>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between border-t border-[#EBEEF5] bg-[#FAFAFA] px-5 py-3">
              <span className="text-[11px] text-[#909399]">
                创建后仍可继续上传文档、微调描述和调整接入配置。
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={saving}
                  className="rounded-[5px] border border-[#DCDFE6] bg-white px-4 py-2 text-[13px] text-[#606266] hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
                  onClick={closeDialog}
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={saving}
                  className="rounded-[5px] bg-[#409EFF] px-5 py-2 text-[13px] text-white hover:bg-[#66b1ff] disabled:opacity-50"
                  onClick={() => void submitForm()}
                >
                  {saving ? "保存中…" : dialogMode === "create" ? "创建" : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
