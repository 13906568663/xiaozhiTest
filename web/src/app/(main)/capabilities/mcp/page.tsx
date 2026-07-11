"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BadgeInfo,
  Cable,
  ShieldCheck,
  Info,
  Plug,
  CirclePlus,
  X,
  Search,
  Check,
  Settings2,
} from "lucide-react";

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

type TabMode = "external" | "virtual";

type MountedTool = {
  name: string;
  method: string;
  description: string;
  response_path?: string;
  response_pick?: Record<string, string[]>;
  [key: string]: unknown;
};

const MOUNTED_TOOL_BASE_KEYS = ["name", "method", "description"] as const;

function extractAdvancedJson(tool: MountedTool): string {
  const rest: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(tool)) {
    if (!MOUNTED_TOOL_BASE_KEYS.includes(key as (typeof MOUNTED_TOOL_BASE_KEYS)[number])) {
      rest[key] = value;
    }
  }
  return Object.keys(rest).length === 0 ? "{}" : JSON.stringify(rest, null, 2);
}

function hasAdvancedConfig(tool: MountedTool): boolean {
  return Object.keys(tool).some(
    (key) => !MOUNTED_TOOL_BASE_KEYS.includes(key as (typeof MOUNTED_TOOL_BASE_KEYS)[number]),
  );
}

const ADVANCED_EXAMPLE_JSON = `{
  "response_path": "$.data",
  "response_pick": {
    "$.data.joints": ["NAME"],
    "$.data.sites": ["NAME"],
    "$.data.strongholds": ["NAME"]
  }
}`;

type ToolsetItem = {
  id: string;
  name: string;
  description: string | null;
  method: string;
  url: string;
  status: string;
};

const METHOD_COLORS: Record<string, string> = {
  POST: "#ECF5FF",
  PUT: "#FDF6EC",
  GET: "#F0F9EB",
  DELETE: "#FEF0F0",
  PATCH: "#F0F9EB",
};

const METHOD_TEXT: Record<string, string> = {
  POST: "#409EFF",
  PUT: "#E6A23C",
  GET: "#67C23A",
  DELETE: "#F56C6C",
  PATCH: "#67C23A",
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
  const [tabMode, setTabMode] = useState<TabMode>("external");
  const [mountedTools, setMountedTools] = useState<MountedTool[]>([]);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerItems, setPickerItems] = useState<ToolsetItem[]>([]);
  const [pickerTotal, setPickerTotal] = useState(0);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerPage, setPickerPage] = useState(1);
  const [pickerSelected, setPickerSelected] = useState<Map<string, MountedTool>>(new Map());

  const [advancedDialog, setAdvancedDialog] = useState<{
    open: boolean;
    toolIdx: number | null;
    toolName: string;
    draft: string;
    error: string | null;
  }>({
    open: false,
    toolIdx: null,
    toolName: "",
    draft: "{}",
    error: null,
  });
  const pickerSearchRef = useRef<HTMLInputElement>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [mcpRes, virtualRes] = await Promise.all([
        apiClient.get<McpItem[]>("/capabilities", { params: { type: "mcp" } }),
        apiClient.get<McpItem[]>("/capabilities", { params: { type: "virtual_mcp" } }),
      ]);
      setItems([...mcpRes.data, ...virtualRes.data]);
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
    setTabMode("external");
    setMountedTools([]);
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
    const tools = Array.isArray(cfg.mounted_tools) ? (cfg.mounted_tools as MountedTool[]) : [];
    setMountedTools(tools);
    setFormErrors({});
    setTabMode(item.type === "virtual_mcp" ? "virtual" : "external");
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const errors: Record<string, string> = {};
    if (!form.code.trim()) errors.code = "编码不能为空";
    if (!form.name.trim()) errors.name = "名称不能为空";

    if (tabMode === "external") {
      if (!form.url.trim()) errors.url = "URL / Address 不能为空";
      if (form.timeout.trim() && (isNaN(Number(form.timeout)) || Number(form.timeout) < 1))
        errors.timeout = "超时秒数必须为正整数";
    }

    if (tabMode === "virtual" && mountedTools.length === 0) {
      errors._submit = "动态工具集至少需要挂载一个接口";
    }

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
    if (tabMode === "virtual" && mountedTools.length > 0) {
      configJson.mounted_tools = mountedTools;
    }
    const payload = {
      type: tabMode === "virtual" ? "virtual_mcp" : "mcp",
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

  const pickerPageSize = 10;

  const fetchToolsets = useCallback(async (search: string, pg: number) => {
    setPickerLoading(true);
    try {
      const res = await apiClient.get<{ items: ToolsetItem[]; total: number }>("/toolsets", {
        params: {
          name: search || undefined,
          status: "active",
          page: pg,
          page_size: pickerPageSize,
        },
      });
      setPickerItems(res.data.items);
      setPickerTotal(res.data.total);
    } catch {
      setPickerItems([]);
      setPickerTotal(0);
    } finally {
      setPickerLoading(false);
    }
  }, []);

  const openPicker = () => {
    setPickerSearch("");
    setPickerPage(1);
    setPickerSelected(new Map());
    setPickerOpen(true);
    void fetchToolsets("", 1);
    setTimeout(() => pickerSearchRef.current?.focus(), 100);
  };

  const handlePickerSearch = (val: string) => {
    setPickerSearch(val);
    setPickerPage(1);
    void fetchToolsets(val, 1);
  };

  const handlePickerPageChange = (pg: number) => {
    setPickerPage(pg);
    void fetchToolsets(pickerSearch, pg);
  };

  const togglePickerItem = (tool: ToolsetItem) => {
    setPickerSelected((prev) => {
      const next = new Map(prev);
      if (next.has(tool.id)) {
        next.delete(tool.id);
      } else {
        next.set(tool.id, {
          name: tool.name,
          method: tool.method,
          description: tool.description || "",
        });
      }
      return next;
    });
  };

  const confirmPicker = () => {
    const existing = new Set(mountedTools.map((tool) => tool.name));
    const toAdd = [...pickerSelected.values()].filter((tool) => !existing.has(tool.name));
    setMountedTools((prev) => [...prev, ...toAdd]);
    setPickerOpen(false);
  };

  const openAdvancedDialog = (idx: number) => {
    const tool = mountedTools[idx];
    if (!tool) return;
    setAdvancedDialog({
      open: true,
      toolIdx: idx,
      toolName: tool.name,
      draft: extractAdvancedJson(tool),
      error: null,
    });
  };

  const closeAdvancedDialog = () => {
    setAdvancedDialog({
      open: false,
      toolIdx: null,
      toolName: "",
      draft: "{}",
      error: null,
    });
  };

  const validateAdvancedDraft = (raw: string): Record<string, unknown> | null => {
    const text = raw.trim();
    if (!text || text === "{}") return {};

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setAdvancedDialog((state) => ({
        ...state,
        error: `JSON 格式错误：${(e as Error).message}`,
      }));
      return null;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setAdvancedDialog((state) => ({
        ...state,
        error: "顶层必须是 JSON 对象（{ ... }）",
      }));
      return null;
    }

    const obj = parsed as Record<string, unknown>;
    for (const key of MOUNTED_TOOL_BASE_KEYS) {
      if (key in obj) {
        setAdvancedDialog((state) => ({
          ...state,
          error: `高级配置不能包含 "${key}"（这是基础字段，由列表项管理）`,
        }));
        return null;
      }
    }

    if ("response_path" in obj) {
      const responsePath = obj.response_path;
      if (typeof responsePath !== "string") {
        setAdvancedDialog((state) => ({ ...state, error: "response_path 必须是字符串" }));
        return null;
      }
      const trimmed = responsePath.trim();
      if (trimmed && trimmed !== "$" && !trimmed.startsWith("$.")) {
        setAdvancedDialog((state) => ({
          ...state,
          error: 'response_path 必须以 "$." 开头，例如 "$.data"',
        }));
        return null;
      }
    }

    if ("response_pick" in obj) {
      const responsePick = obj.response_pick;
      if (
        typeof responsePick !== "object" ||
        responsePick === null ||
        Array.isArray(responsePick)
      ) {
        setAdvancedDialog((state) => ({
          ...state,
          error: "response_pick 必须是 JSON 对象",
        }));
        return null;
      }
      for (const [path, fields] of Object.entries(responsePick as Record<string, unknown>)) {
        if (path !== "$" && !path.startsWith("$.")) {
          setAdvancedDialog((state) => ({
            ...state,
            error: `response_pick 中的路径 "${path}" 必须以 "$." 开头`,
          }));
          return null;
        }
        if (!Array.isArray(fields) || !fields.every((field) => typeof field === "string")) {
          setAdvancedDialog((state) => ({
            ...state,
            error: `response_pick["${path}"] 必须是字符串数组（要保留的字段名）`,
          }));
          return null;
        }
      }
    }

    return obj;
  };

  const applyAdvancedDialog = () => {
    const parsed = validateAdvancedDraft(advancedDialog.draft);
    const idx = advancedDialog.toolIdx;
    if (parsed === null || idx === null) return;

    setMountedTools((tools) => {
      const next = [...tools];
      const current = next[idx];
      if (!current) return tools;
      next[idx] = {
        name: current.name,
        method: current.method,
        description: current.description,
        ...parsed,
      };
      return next;
    });
    closeAdvancedDialog();
  };

  const formatAdvancedDraft = () => {
    try {
      const obj = JSON.parse(advancedDialog.draft);
      setAdvancedDialog((state) => ({
        ...state,
        draft: JSON.stringify(obj, null, 2),
        error: null,
      }));
    } catch (e) {
      setAdvancedDialog((state) => ({
        ...state,
        error: `无法格式化：${(e as Error).message}`,
      }));
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

  const mcpTypeLabel = (type: string) =>
    type === "virtual_mcp" ? "动态工具集" : type === "mcp" ? "外部 MCP" : type;

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
      key: "type",
      title: "类型",
      width: 100,
      align: "center",
      render: (_v, row) => {
        const isVirtual = row.type === "virtual_mcp";
        return (
          <span
            className={cn(
              "inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold",
              isVirtual
                ? "bg-[#FDF6EC] text-[#E6A23C]"
                : "bg-[#ECF5FF] text-[#409EFF]",
            )}
          >
            {mcpTypeLabel(row.type)}
          </span>
        );
      },
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

              <div className="flex flex-col gap-[5px]">
                <FieldLabel label="MCP 类型" required desc="选择要创建的 MCP 类型" />
                <Select
                  value={tabMode}
                  onChange={(e) => setTabMode(e.target.value as TabMode)}
                  options={[
                    { value: "external", label: "外部 MCP 服务 — 连接已有的 MCP 服务端点" },
                    { value: "virtual", label: "动态工具集 — 将多个接口组装为虚拟 MCP" },
                  ]}
                />
              </div>

              {tabMode === "external" && (
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
              )}

              {tabMode === "virtual" && (
                <>
                  <div className="flex flex-col gap-3 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
                    <SectionLabel
                      tag="IDENTITY"
                      title="基本信息"
                      icon={<BadgeInfo className="h-[15px] w-[15px] text-[#409EFF]" />}
                      iconWrap
                    />
                    <div className="flex gap-3.5">
                      <FormField label="编码" required error={formErrors.code} className="flex-1">
                        <Input
                          value={form.code}
                          onChange={(e) => set("code", e.target.value)}
                          placeholder="请输入编码，如 ticket_mcp"
                          disabled={!!editing}
                        />
                      </FormField>
                      <FormField label="名称" required error={formErrors.name} className="flex-1">
                        <Input
                          value={form.name}
                          onChange={(e) => set("name", e.target.value)}
                          placeholder="请输入名称，如工单管理 MCP"
                        />
                      </FormField>
                      <div className="w-[180px]">
                        <FormField label="状态">
                          <Select
                            value={form.status}
                            onChange={(e) => set("status", e.target.value)}
                            options={[
                              { value: "active", label: "active" },
                              { value: "inactive", label: "inactive" },
                            ]}
                          />
                        </FormField>
                      </div>
                    </div>
                    <FormField label="描述">
                      <Input
                        value={form.description}
                        onChange={(e) => set("description", e.target.value)}
                        placeholder="请输入动态工具集说明"
                      />
                    </FormField>
                  </div>

                  <div className="h-px bg-[#EBEEF5]" />

                  <div className="flex flex-col gap-3 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
                    <SectionLabel
                      tag="CONNECTION"
                      title="全局配置"
                      icon={<Cable className="h-[15px] w-[15px] text-[#409EFF]" />}
                      iconWrap={false}
                    />
                    <FormField label="HTTP Header" hint="全局生效" error={formErrors.headers}>
                      <Textarea
                        className="min-h-[52px] font-mono text-xs"
                        value={form.headers}
                        onChange={(e) => set("headers", e.target.value)}
                        placeholder='{"X-App-Id":"agent-flow"}'
                      />
                    </FormField>
                  </div>

                  <div className="h-px bg-[#EBEEF5]" />

                  <div className="flex flex-col gap-2.5 rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-4 py-3.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <Plug className="h-[14px] w-[14px] text-[#409EFF]" />
                        <span className="text-[13px] font-semibold text-[#303133]">挂载接口</span>
                        {mountedTools.length > 0 && (
                          <div className="flex h-[18px] items-center justify-center rounded-full bg-[#ECF5FF] px-2">
                            <span className="text-[11px] font-semibold text-[#409EFF]">
                              {mountedTools.length}
                            </span>
                          </div>
                        )}
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="border-[var(--el-primary)] text-[var(--el-primary)] hover:bg-[var(--el-primary-light-9)]"
                        onClick={openPicker}
                      >
                        <CirclePlus className="h-3 w-3" />
                        选择接口
                      </Button>
                    </div>

                    {mountedTools.length > 0 ? (
                      <div className="rounded-[6px] border border-[#EBEEF5]">
                        {mountedTools.map((tool, idx) => {
                          const advanced = hasAdvancedConfig(tool);
                          return (
                            <div
                              key={`${tool.name}-${idx}`}
                              className={cn(
                                "flex min-h-[38px] items-center justify-between px-3 py-1",
                                idx < mountedTools.length - 1 && "border-b border-[#EBEEF5]",
                              )}
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="text-[12px] font-[500] text-[#303133]">
                                  {tool.name}
                                </span>
                                <div
                                  className="rounded-[3px] px-1.5 py-0.5 text-[11px] font-[500]"
                                  style={{
                                    background: METHOD_COLORS[tool.method] ?? "#F5F7FA",
                                    color: METHOD_TEXT[tool.method] ?? "#606266",
                                  }}
                                >
                                  {tool.method}
                                </div>
                                {advanced && (
                                  <div className="flex items-center gap-1 rounded-[3px] bg-[#ECF5FF] px-1.5 py-0.5 text-[10px] font-[500] text-[#409EFF]">
                                    <Settings2 className="h-2.5 w-2.5" />
                                    已配置
                                  </div>
                                )}
                                <span className="text-[11px] text-[#DCDFE6]">—</span>
                                <span className="truncate text-[12px] text-[#909399]">
                                  {tool.description}
                                </span>
                              </div>
                              <div className="flex shrink-0 items-center gap-0.5">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className={cn(
                                    "h-6 gap-1 px-2 text-[11px] font-[500]",
                                    advanced
                                      ? "text-[#409EFF] hover:bg-[#ECF5FF]"
                                      : "text-[#909399] hover:bg-[#F5F7FA]",
                                  )}
                                  onClick={() => openAdvancedDialog(idx)}
                                  title="编辑此接口的响应抽取或字段裁剪配置"
                                >
                                  <Settings2 className="h-3 w-3" />
                                  高级
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-6 text-[var(--el-text-placeholder)] hover:text-[var(--el-text-secondary)]"
                                  onClick={() =>
                                    setMountedTools((tools) =>
                                      tools.filter((_, toolIdx) => toolIdx !== idx),
                                    )
                                  }
                                  title="移除接口"
                                >
                                  <X className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded-[6px] border border-dashed border-[#DCDFE6] py-4 text-center text-[12px] text-[#C0C4CC]">
                        暂未挂载接口，点击「选择接口」添加
                      </div>
                    )}
                  </div>

                  <div className="h-px bg-[#EBEEF5]" />
                  {authSection}
                </>
              )}

        </div>
      </Dialog>

      <Dialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="选择接口"
        description="从已注册的工具集中选择需要挂载的接口"
        width={640}
        footer={
          <>
            <span className="mr-auto text-xs text-[#909399]">
              已选 <span className="font-semibold text-[#409EFF]">{pickerSelected.size}</span> 项
            </span>
            <Button variant="secondary" size="sm" onClick={() => setPickerOpen(false)}>
              取消
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={pickerSelected.size === 0}
              onClick={confirmPicker}
            >
              确认添加
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#C0C4CC]" />
            <input
              ref={pickerSearchRef}
              type="text"
              className="h-9 w-full rounded-md border border-[#DCDFE6] bg-white pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-[#C0C4CC] focus:border-[#409EFF]"
              placeholder="搜索接口名称…"
              value={pickerSearch}
              onChange={(e) => handlePickerSearch(e.target.value)}
            />
          </div>

          <div className={cn("rounded-md border border-[#EBEEF5]", pickerLoading && "opacity-60")}>
            {pickerItems.length === 0 ? (
              <div className="py-10 text-center text-sm text-[#C0C4CC]">
                {pickerLoading ? "加载中…" : "暂无可用接口"}
              </div>
            ) : (
              pickerItems.map((tool) => {
                const alreadyMounted = mountedTools.some((mounted) => mounted.name === tool.name);
                const selected = pickerSelected.has(tool.id);
                return (
                  <div
                    key={tool.id}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 border-b border-[#EBEEF5] px-3.5 py-2.5 transition-colors last:border-b-0",
                      alreadyMounted
                        ? "cursor-not-allowed bg-[#FAFAFA] opacity-50"
                        : selected
                          ? "bg-[#ECF5FF]"
                          : "hover:bg-[#F5F7FA]",
                    )}
                    onClick={() => {
                      if (!alreadyMounted) togglePickerItem(tool);
                    }}
                  >
                    <div
                      className={cn(
                        "flex size-[18px] shrink-0 items-center justify-center rounded border transition-colors",
                        alreadyMounted
                          ? "border-[#DCDFE6] bg-[#F5F7FA]"
                          : selected
                            ? "border-[#409EFF] bg-[#409EFF]"
                            : "border-[#DCDFE6] bg-white",
                      )}
                    >
                      {(selected || alreadyMounted) && <Check className="size-3 text-white" />}
                    </div>

                    <div
                      className="shrink-0 rounded-[3px] px-1.5 py-0.5 text-[11px] font-medium"
                      style={{
                        background: METHOD_COLORS[tool.method] ?? "#F5F7FA",
                        color: METHOD_TEXT[tool.method] ?? "#606266",
                      }}
                    >
                      {tool.method}
                    </div>

                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="text-[13px] font-medium text-[#303133]">{tool.name}</span>
                      {tool.description && (
                        <span
                          className="truncate text-[11px] text-[#909399]"
                          title={tool.description}
                        >
                          {tool.description}
                        </span>
                      )}
                    </div>

                    {alreadyMounted && (
                      <span className="shrink-0 text-[11px] text-[#C0C4CC]">已挂载</span>
                    )}
                  </div>
                );
              })
            )}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-[#909399]">共 {pickerTotal} 个接口</span>
            {pickerTotal > pickerPageSize && (
              <Pagination
                current={pickerPage}
                pageSize={pickerPageSize}
                total={pickerTotal}
                onChange={handlePickerPageChange}
              />
            )}
          </div>
        </div>
      </Dialog>

      <Dialog
        open={advancedDialog.open}
        onClose={closeAdvancedDialog}
        title={`高级配置 · ${advancedDialog.toolName}`}
        description="为此挂载接口配置响应抽取、字段裁剪等"
        width={620}
        footer={
          <div className="flex items-center justify-between gap-3 px-5 py-3">
            <div className="text-[11px] text-[#909399]">
              留空或 <code className="rounded bg-[#F5F7FA] px-1">{"{}"}</code>{" "}
              表示清除该接口的高级配置
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={closeAdvancedDialog}>
                取消
              </Button>
              <Button variant="primary" size="sm" onClick={applyAdvancedDialog}>
                <Check className="h-3.5 w-3.5" />
                确定
              </Button>
            </div>
          </div>
        }
      >
        <div className="flex flex-col gap-3 px-5 py-4">
          <div className="rounded-[6px] border border-[#EBEEF5] bg-[#FAFAFA] px-3 py-2.5 text-[11px] leading-relaxed text-[#606266]">
            <div className="mb-1 flex items-center gap-1.5 font-[500] text-[#303133]">
              <Info className="h-3 w-3 text-[#409EFF]" />
              <span>支持的字段</span>
            </div>
            <ul className="ml-4 list-disc space-y-0.5">
              <li>
                <code className="rounded bg-white px-1 text-[10px] text-[#E6A23C]">
                  response_path
                </code>
                ：响应抽取路径（如{" "}
                <code className="rounded bg-white px-1 text-[10px]">$.data</code>
                ），调用后先抽出此路径子树再返回。
              </li>
              <li>
                <code className="rounded bg-white px-1 text-[10px] text-[#E6A23C]">
                  response_pick
                </code>
                ：字段裁剪。key 为{" "}
                <code className="rounded bg-white px-1 text-[10px]">$.路径</code>
                ，value 为要保留的字段名数组。
              </li>
            </ul>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-[500] text-[#606266]">JSON 配置</span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[11px] text-[#909399] hover:text-[#409EFF]"
                  onClick={() =>
                    setAdvancedDialog((state) => ({
                      ...state,
                      draft: ADVANCED_EXAMPLE_JSON,
                      error: null,
                    }))
                  }
                  type="button"
                >
                  填入示例
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[11px] text-[#909399] hover:text-[#409EFF]"
                  onClick={formatAdvancedDraft}
                  type="button"
                >
                  格式化
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[11px] text-[#909399] hover:text-[#F56C6C]"
                  onClick={() =>
                    setAdvancedDialog((state) => ({
                      ...state,
                      draft: "{}",
                      error: null,
                    }))
                  }
                  type="button"
                >
                  清空
                </Button>
              </div>
            </div>
            <Textarea
              value={advancedDialog.draft}
              onChange={(e) =>
                setAdvancedDialog((state) => ({
                  ...state,
                  draft: e.target.value,
                  error: null,
                }))
              }
              rows={12}
              spellCheck={false}
              className="font-mono text-[12px] leading-[1.55]"
              placeholder={ADVANCED_EXAMPLE_JSON}
            />
            {advancedDialog.error && (
              <div className="rounded-[4px] border border-[#FBC4C4] bg-[#FEF0F0] px-2.5 py-1.5 text-[11px] text-[#F56C6C]">
                {advancedDialog.error}
              </div>
            )}
          </div>
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
