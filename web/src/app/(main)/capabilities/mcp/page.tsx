"use client";

import { useCallback, useEffect, useState } from "react";
import { BadgeInfo, Cable, ShieldCheck, Info } from "lucide-react";

import { apiClient } from "@/lib/api";
import { ActionButtons } from "@/components/ui/action-buttons";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { FilterBar } from "@/components/ui/filter-bar";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { Select } from "@/components/ui/select";
import { StatCard } from "@/components/ui/stat-card";
import { Textarea } from "@/components/ui/textarea";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { toast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { useFormErrors } from "@/hooks/use-form-errors";

type McpItem = {
  id: string;
  type: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  created_by?: string;
};

const EMPTY_FORM = {
  code: "",
  name: "",
  description: "",
  status: "active",
  url: "",
  command: "",
  args: "",
  env: "",
  transport: "streamable_http",
  client_type: "http_stateless",
  timeout: "30",
  headers: "",
  request_params: "",
  auth_type: "none",
  auth_tool: "",
  auth_credentials: "",
  token_field: "",
  inject_header: "",
  token_prefix: "",
};

/* ──────────────────────────────────────────────────────────────
   小型子组件
────────────────────────────────────────────────────────────── */

function SectionLabel({ tag, title, icon, iconWrap = true }: {
  tag: string;
  title: string;
  icon: React.ReactNode;
  iconWrap?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5">
      {iconWrap ? (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[6px] bg-[#ECF5FF]">
          {icon}
        </div>
      ) : icon}
      <div className="flex flex-col gap-0">
        <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[#C0C4CC]">{tag}</span>
        <span className="text-[14px] font-semibold text-[#303133]">{title}</span>
      </div>
    </div>
  );
}

function FieldLabel({ label, required, desc, descRight }: {
  label: string;
  required?: boolean;
  desc?: string;
  descRight?: string;
}) {
  return (
    <div className="flex flex-col gap-[3px]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-0.5">
          <span className="text-[12px] font-[500] text-[#606266]">{label}</span>
          {required && <span className="text-[12px] text-[#F56C6C]">*</span>}
        </div>
        {descRight && <span className="text-[10px] text-[#C0C4CC]">{descRight}</span>}
      </div>
      {desc && <span className="text-[11px] text-[#C0C4CC]">{desc}</span>}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   主页面
────────────────────────────────────────────────────────────── */

export default function McpListPage() {
  const [items, setItems] = useState<McpItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [nameDraft, setNameDraft] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [creatorDraft, setCreatorDraft] = useState("");
  const [creatorFilter, setCreatorFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<McpItem | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const { errors: formErrors, setErrors: setFormErrors, clearErrors: clearFormErrors } = useFormErrors();
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<McpItem[]>("/capabilities", {
        params: { type: "mcp" },
      });
      setItems(data);
    } catch {
      /* silently handle */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const filtered = items.filter((item) => {
    if (nameFilter && !item.name.toLowerCase().includes(nameFilter.toLowerCase()) && !item.code.toLowerCase().includes(nameFilter.toLowerCase())) return false;
    if (creatorFilter) {
      const by = (item.created_by ?? "").toLowerCase();
      if (!by.includes(creatorFilter.toLowerCase())) return false;
    }
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  const set = (key: string, val: string) => {
    clearFormErrors(key);
    setForm((f) => ({ ...f, [key]: val }));
  };

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormErrors({});
    setDialogOpen(true);
  };

  const openEdit = (item: McpItem) => {
    setEditing(item);
    const cfg = item.config_json || {};
    setForm({
      code: item.code,
      name: item.name,
      description: item.description || "",
      status: item.status,
      url: String(cfg.url || ""),
      command: String(cfg.command || ""),
      args: Array.isArray(cfg.args) ? (cfg.args as string[]).join("\n") : "",
      env: cfg.env ? JSON.stringify(cfg.env, null, 2) : "",
      transport: String(cfg.transport || "streamable_http"),
      client_type: String(cfg.client_type || "http_stateless"),
      timeout: String(cfg.timeout || "30"),
      headers: cfg.headers ? JSON.stringify(cfg.headers, null, 2) : "",
      request_params: cfg.request_params ? JSON.stringify(cfg.request_params, null, 2) : "",
      auth_type: String(cfg.auth_type || "none"),
      auth_tool: String(cfg.auth_tool || ""),
      auth_credentials: String(cfg.auth_credentials || ""),
      token_field: String(cfg.token_field || ""),
      inject_header: String(cfg.inject_header || ""),
      token_prefix: String(cfg.token_prefix || ""),
    });
    setFormErrors({});
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const errors: Record<string, string> = {};
    if (!form.code.trim()) errors.code = "编码不能为空";
    if (!form.name.trim()) errors.name = "名称不能为空";

    if (!form.url.trim()) errors.url = "URL / Address 不能为空";
    if (form.timeout.trim() && (isNaN(Number(form.timeout)) || Number(form.timeout) < 1))
      errors.timeout = "超时秒数必须为正整数";

    if (form.auth_type === "api_key" && !form.auth_credentials.trim())
      errors.auth_credentials = "API Key 不能为空";
    if (form.auth_type === "bearer" && !form.auth_credentials.trim())
      errors.auth_credentials = "Bearer Token 不能为空";
    if (form.auth_type === "token_fetch" && !form.auth_tool.trim())
      errors.auth_tool = "认证工具不能为空";

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }

    const configJson: Record<string, unknown> = {};
    if (form.url.trim()) configJson.url = form.url.trim();
    if (form.command.trim()) configJson.command = form.command.trim();
    if (form.args.trim()) configJson.args = form.args.split("\n").map((s) => s.trim()).filter(Boolean);
    if (form.env.trim()) {
      try { configJson.env = JSON.parse(form.env); } catch { setFormErrors({ env: "环境变量必须是合法的 JSON" }); return; }
    }
    if (form.transport) configJson.transport = form.transport;
    if (form.client_type) configJson.client_type = form.client_type;
    if (form.timeout) configJson.timeout = Number(form.timeout);
    if (form.headers.trim()) {
      try { configJson.headers = JSON.parse(form.headers); } catch { setFormErrors({ headers: "Headers 必须是合法的 JSON" }); return; }
    }
    if (form.request_params.trim()) {
      try { configJson.request_params = JSON.parse(form.request_params); } catch { setFormErrors({ request_params: "请求参数必须是合法的 JSON" }); return; }
    }
    if (form.auth_type !== "none") {
      configJson.auth_type = form.auth_type;
      if (form.auth_tool) configJson.auth_tool = form.auth_tool;
      if (form.auth_credentials) configJson.auth_credentials = form.auth_credentials;
      if (form.token_field) configJson.token_field = form.token_field;
      if (form.inject_header) configJson.inject_header = form.inject_header;
      if (form.token_prefix) configJson.token_prefix = form.token_prefix;
    }
    const payload = {
      type: "mcp",
      code: form.code.trim(),
      name: form.name.trim(),
      description: form.description.trim() || null,
      status: form.status,
      config_json: configJson,
    };

    try {
      if (editing) {
        await apiClient.put(`/capabilities/${editing.id}`, payload);
      } else {
        await apiClient.post("/capabilities", payload);
      }
      setDialogOpen(false);
      void fetchData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "保存失败";
      setFormErrors({ _submit: msg });
    }
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    try {
      await apiClient.delete(`/capabilities/${confirmTarget.id}`);
      toast.success("操作成功");
      void fetchData();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setConfirmTarget(null);
    }
  };

  const fmtDate = (d: string) => {
    const dt = new Date(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const day = String(dt.getDate()).padStart(2, "0");
    const h = String(dt.getHours()).padStart(2, "0");
    const min = String(dt.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${day} ${h}:${min}`;
  };

  const handleToggleStatus = async (item: McpItem) => {
    const newStatus = item.status === "active" ? "inactive" : "active";
    try {
      await apiClient.put(`/capabilities/${item.id}`, { ...item, status: newStatus });
      void fetchData();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const activeCount = items.filter((i) => i.status === "active").length;
  const inactiveCount = items.length - activeCount;

  const columns: Column<McpItem>[] = [
    {
      key: "name",
      title: "名称",
      width: 180,
      render: (_v, r) => (
        <div className="flex min-w-0 flex-col justify-center gap-0.5">
          <span className="text-[13px] font-medium text-[#303133]">{r.name}</span>
          {r.description ? (
            <span
              className="block min-w-0 max-w-full truncate text-[11px] text-[#909399]"
              title={r.description}
            >
              {r.description}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "code",
      title: "编码",
      width: 150,
      render: (v) => <span className="text-xs text-[#606266]">{String(v)}</span>,
    },
    {
      key: "config_json",
      title: "关键配置",
      width: 210,
      render: (_v, r) => {
        const cfg = r.config_json || {};
        const transport = `${String(cfg.client_type || "http_stateless")} / ${String(cfg.transport || "streamable_http")}`;
        const url = String(cfg.url || cfg.command || "");
        return (
          <div className="flex min-w-0 flex-col justify-center gap-0.5">
            <span className="text-xs text-[#606266]">{transport}</span>
            {url && (
              <span
                className="block min-w-0 max-w-full truncate text-[11px] text-[#909399]"
                title={url}
              >
                {url}
              </span>
            )}
          </div>
        );
      },
    },
    {
      key: "created_by",
      title: "创建人",
      width: 80,
      render: (v) => <span className="text-xs text-[#606266]">{String(v || "—")}</span>,
    },
    {
      key: "updated_at",
      title: "更新时间",
      width: 140,
      align: "center",
      render: (v) => <span className="text-xs text-[#606266]">{fmtDate(String(v))}</span>,
    },
    {
      key: "created_at",
      title: "创建时间",
      width: 140,
      align: "center",
      render: (v) => <span className="text-xs text-[#606266]">{fmtDate(String(v))}</span>,
    },
    {
      key: "status",
      title: "状态",
      width: 72,
      align: "center",
      render: (_v, r) => (
        <ToggleSwitch
          checked={r.status === "active"}
          onChange={() => void handleToggleStatus(r)}
        />
      ),
    },
    {
      key: "id",
      title: "操作",
      width: 120,
      fixed: "right",
      render: (_v, r) => (
        <ActionButtons
          items={[
            { key: "edit", label: "编辑", onClick: () => openEdit(r) },
            { key: "delete", label: "删除", color: "danger", onClick: () => setConfirmTarget({ id: r.id, name: r.name }) },
          ]}
        />
      ),
    },
  ];

  /* ────────────────────────────────────────────────────────────
     认证配置 Box (外部/虚拟模式共用)
  ──────────────────────────────────────────────────────────── */
  const authBox = form.auth_type !== "none" && (
    <div className="flex flex-col gap-3.5 rounded-[6px] border border-[#E8F2FF] bg-[#F8FBFF] p-4">

      {/* ── api_key：静态密钥 ── */}
      {form.auth_type === "api_key" && (
        <div className="flex gap-3.5">
          <div className="flex flex-1 flex-col gap-[5px]">
            <FieldLabel label="Header 名称" desc="注入的 Header 参数名" />
            <Input
              value={form.inject_header}
              onChange={(e) => set("inject_header", e.target.value)}
              placeholder="如 X-API-Key、Authorization"
            />
          </div>
          <div className="flex flex-1 flex-col gap-[5px]">
            <FieldLabel label="API Key" required desc="将以指定名称注入到请求 Header 中" />
            <Input
              value={form.auth_credentials}
              onChange={(e) => set("auth_credentials", e.target.value)}
              placeholder="请输入 API Key 值"
            />
          </div>
        </div>
      )}

      {/* ── bearer：Bearer Token ── */}
      {form.auth_type === "bearer" && (
        <div className="flex gap-3.5">
          <div className="flex flex-1 flex-col gap-[5px]">
            <FieldLabel label="Bearer Token" required desc="将以 Bearer <token> 格式注入请求 Header" />
            <Input
              value={form.auth_credentials}
              onChange={(e) => set("auth_credentials", e.target.value)}
              placeholder="请输入 Bearer Token 值"
            />
          </div>
          <div className="flex flex-1 flex-col gap-[5px]">
            <FieldLabel label="Header 名称" desc="默认为 Authorization" />
            <Input
              value={form.inject_header}
              onChange={(e) => set("inject_header", e.target.value)}
              placeholder="Authorization"
            />
          </div>
        </div>
      )}

      {/* ── token_fetch：工具动态获取 Token ── */}
      {form.auth_type === "token_fetch" && (
        <>
          <div className="flex items-center gap-1.5">
            <Info className="h-3 w-3 shrink-0 text-[#409EFF]" />
            <span className="text-[11px] text-[#409EFF]">
              token_fetch 模式：系统自动调用指定工具获取 Token，再注入其余工具请求
            </span>
          </div>

          {/* 认证工具（半行） */}
          <div className="flex gap-3.5">
            <div className="flex flex-1 flex-col gap-[5px]">
              <FieldLabel label="认证工具" required desc="选择工具列表中的某个工具来获取 Token" />
              <Input
                value={form.auth_tool}
                onChange={(e) => set("auth_tool", e.target.value)}
                placeholder="请输入认证工具名，如 login"
              />
            </div>
            <div className="flex-1" />
          </div>

          {/* 静态凭证（整行，文本域） */}
          <div className="flex flex-col gap-[5px]">
            <FieldLabel label="静态凭证" descRight="JSON，将作为入参传入认证工具" />
            <Textarea
              className="min-h-[72px] font-mono text-xs"
              value={form.auth_credentials}
              onChange={(e) => set("auth_credentials", e.target.value)}
              placeholder='{"username":"admin","password":"***"}'
            />
          </div>

          {/* Token 提取路径 + Header 名称（各占半行） */}
          <div className="flex gap-3.5">
          <div className="flex flex-1 flex-col gap-[5px]">
              <FieldLabel label="Header 名称" desc="将 Token 注入到其他工具请求的 Header" />
              <Input
                value={form.inject_header}
                onChange={(e) => set("inject_header", e.target.value)}
                placeholder="请输入 Header 名，如 Authorization"
              />
            </div>
            <div className="flex flex-1 flex-col gap-[5px]">
              <FieldLabel label="Token 提取路径" desc="从响应中提取 Token 的 JSON 路径" />
              <Input
                value={form.token_field}
                onChange={(e) => set("token_field", e.target.value)}
                placeholder="请输入 Token 路径，如 data.access_token"
              />
            </div>
          </div>

          {/* 认证执行流程预览 */}
          <div className="flex items-center gap-3 rounded-[6px] border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2">
            <span className="shrink-0 text-[11px] font-semibold text-[#92400E]">认证执行流程</span>
            <span className="text-[11px] text-[#92400E]">
              调用 <span className="font-medium">{form.auth_tool || "login"}</span> 工具
              {" → "}提取 <span className="font-medium">{form.token_field || "data.access_token"}</span>
              {" → "}注入到 Header <span className="font-medium">{form.inject_header || "Authorization"}</span> …
            </span>
          </div>
        </>
      )}
    </div>
  );

  /* ────────────────────────────────────────────────────────────
     认证配置 Section (外部/虚拟模式共用)
  ──────────────────────────────────────────────────────────── */
  const authSection = (
    <div className="flex flex-col gap-4 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
      <SectionLabel
        tag="AUTH"
        title="认证配置"
        icon={<ShieldCheck className="h-[15px] w-[15px] text-[#409EFF]" />}
        iconWrap
      />

      <div className="flex flex-col gap-[5px]">
        <span className="text-[12px] font-[500] text-[#606266]">认证方式</span>
        <Select
          value={form.auth_type}
          onChange={(e) => set("auth_type", e.target.value)}
          options={[
            { value: "none", label: "无认证" },
            { value: "token_fetch", label: "token_fetch — 工具获取 Token" },
            { value: "api_key", label: "api_key — 静态密钥" },
            { value: "bearer", label: "bearer — Bearer Token" },
          ]}
        />
      </div>

      {authBox}
    </div>
  );

  /* ────────────────────────────────────────────────────────────
     JSX
  ──────────────────────────────────────────────────────────── */
  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="MCP 工具"
        description="管理全局 MCP 连接配置、调用参数和能力编码。"
        breadcrumb={[{ label: "工具能力中心" }, { label: "MCP 工具" }]}
      />

      {/* 统计卡片 */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard title="总配置" value={items.length} />
        <StatCard title="Active" value={<span className="text-[#67C23A]">{activeCount}</span>} />
        <StatCard title="非 Active" value={<span className="text-[#F56C6C]">{inactiveCount}</span>} />
      </div>

      {/* 表格区域 */}
      <div className={cn("flex flex-col gap-3.5 rounded-md border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3", loading && "opacity-70")}>
        <FilterBar
          fields={[
            {
              key: "creator",
              label: "创建人",
              render: () => (
                <Input
                  className="h-8 border-[#DCDCDC]"
                  placeholder="请输入创建人"
                  value={creatorDraft}
                  onChange={(e) => setCreatorDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { setCreatorFilter(creatorDraft); setPage(1); } }}
                />
              ),
            },
            {
              key: "nameFilter",
              label: "名称",
              render: () => (
                <Input
                  className="h-8 border-[#DCDCDC]"
                  placeholder="请输入名称"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { setNameFilter(nameDraft); setPage(1); } }}
                />
              ),
            },
          ]}
          onSearch={() => { setNameFilter(nameDraft); setCreatorFilter(creatorDraft); setPage(1); }}
          onReset={() => { setNameDraft(""); setNameFilter(""); setCreatorDraft(""); setCreatorFilter(""); setPage(1); }}
          extra={
            <Button variant="success" size="sm" onClick={openCreate}>
              新增
            </Button>
          }
        />

        <DataTable
          columns={columns}
          data={paginated}
          rowKey="id"
          emptyText={loading ? "加载中…" : "暂无数据"}
          headerClassName="bg-[#FAFAFA]"
        />
        <Pagination
          className="px-3"
          current={safePage}
          pageSize={pageSize}
          total={filtered.length}
          onChange={setPage}
          onPageSizeChange={(s) => { setPageSize(s); setPage(1); }}
        />
      </div>

      {/* ─── MCP 新建/编辑弹窗 ─── */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={editing ? "编辑 MCP" : "新建 MCP"}
        width={840}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={() => void handleSave()}>
              保存
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5">
              {formErrors._submit && (
                <div className="rounded bg-[#FEF0F0] px-3 py-2 text-xs text-[#F56C6C]">
                  {formErrors._submit}
                </div>
              )}

              {/* 外部 MCP 服务 */}
                <>
                  {/* Section 1: 基本信息 */}
                  <div className="flex flex-col gap-3 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
                    <SectionLabel
                      tag="IDENTITY"
                      title="基本信息"
                      icon={<BadgeInfo className="h-[15px] w-[15px] text-[#409EFF]" />}
                      iconWrap
                    />

                    {/* Row 1: 编码 + 名称 */}
                    <div className="flex gap-3.5">
                      <FormField label="编码" required error={formErrors.code} className="flex-1">
                        <Input
                          value={form.code}
                          onChange={(e) => set("code", e.target.value)}
                          placeholder="请输入编码"
                          disabled={!!editing}
                        />
                      </FormField>
                      <FormField label="名称" required error={formErrors.name} className="flex-1">
                        <Input
                          value={form.name}
                          onChange={(e) => set("name", e.target.value)}
                          placeholder="请输入名称"
                        />
                      </FormField>
                    </div>

                    {/* Row 2: 状态 + 描述 */}
                    <div className="flex gap-3.5">
                      <FormField label="状态" className="flex-1">
                        <Select
                          value={form.status}
                          onChange={(e) => set("status", e.target.value)}
                          options={[
                            { value: "active", label: "active" },
                            { value: "inactive", label: "inactive" },
                          ]}
                        />
                      </FormField>
                      <FormField label="描述" className="flex-1">
                        <Input
                          value={form.description}
                          onChange={(e) => set("description", e.target.value)}
                          placeholder="请输入描述，如探测链路可用性"
                        />
                      </FormField>
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="h-px bg-[#EBEEF5]" />

                  {/* Section 2: MCP 接入 */}
                  <div className="flex flex-col gap-3 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
                    <SectionLabel
                      tag="CONNECTION"
                      title="MCP 接入"
                      icon={<Cable className="h-[15px] w-[15px] text-[#409EFF]" />}
                      iconWrap={false}
                    />

                    {/* Row 1: Client 类型 + Transport */}
                    <div className="flex gap-3.5">
                      <FormField label="Client 类型" className="flex-1">
                        <Select
                          value={form.client_type}
                          onChange={(e) => set("client_type", e.target.value)}
                          options={[
                            { value: "http_stateless", label: "http_stateless" },
                            { value: "http_address", label: "http_address" },
                            { value: "stdio", label: "stdio" },
                          ]}
                        />
                      </FormField>
                      <FormField label="Transport" className="flex-1">
                        <Select
                          value={form.transport}
                          onChange={(e) => set("transport", e.target.value)}
                          options={[
                            { value: "streamable_http", label: "streamable_http" },
                            { value: "sse", label: "sse" },
                            { value: "stdio", label: "stdio" },
                          ]}
                        />
                      </FormField>
                    </div>

                    {/* URL field */}
                    <FormField label="URL / Address" required error={formErrors.url}>
                      <Input
                        value={form.url}
                        onChange={(e) => set("url", e.target.value)}
                        placeholder="请输入 URL，如 https://mcp.example.com/network"
                      />
                    </FormField>

                    {/* Row 2: 超时秒数 */}
                    <div className="flex gap-3.5">
                      <FormField label="超时秒数" className="flex-1">
                        <Input
                          value={form.timeout}
                          onChange={(e) => set("timeout", e.target.value)}
                          placeholder="请输入超时秒数，如 30"
                        />
                      </FormField>
                      <div className="flex-1" />
                    </div>

                    {/* Row: 请求 Header + 请求参数 */}
                    <div className="flex gap-3">
                      <FormField label="请求 Header" hint="覆盖全局" error={formErrors.headers} className="flex-1">
                        <Textarea
                          className="min-h-[48px] font-mono text-xs"
                          value={form.headers}
                          onChange={(e) => set("headers", e.target.value)}
                          placeholder="请输入请求 Header，如 X-Priority=high"
                        />
                      </FormField>
                      <FormField label="请求参数" hint="覆盖全局" error={formErrors.request_params} className="flex-1">
                        <Textarea
                          className="min-h-[48px] font-mono text-xs"
                          value={form.request_params}
                          onChange={(e) => set("request_params", e.target.value)}
                          placeholder="请输入请求参数，如 source=agent"
                        />
                      </FormField>
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="h-px bg-[#EBEEF5]" />

                  {/* Section 3: 认证配置 */}
                  {authSection}
                </>

        </div>
      </Dialog>

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
