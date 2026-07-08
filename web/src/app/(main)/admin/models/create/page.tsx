"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Settings2, X } from "lucide-react";

import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  defaultModelEntry,
  ModelItemDialog,
  type ModelEntry,
} from "../_components/model-item-dialog";

function parseContextWindow(value: string): number | null {
  const t = value.trim().toLowerCase();
  if (!t) return null;
  if (t.endsWith("k")) {
    const n = Number.parseFloat(t.slice(0, -1));
    return Number.isFinite(n) ? Math.round(n * 1000) : null;
  }
  const n = Number.parseInt(t, 10);
  return Number.isFinite(n) ? n : null;
}

function serializeCatalogItem(m: ModelEntry): Record<string, unknown> {
  const id = m.model_name.trim();
  const ctx = parseContextWindow(m.context_window);
  const caps = m.capabilities;
  const capabilitiesObj =
    Array.isArray(caps) && caps.length > 0
      ? {
          vision: caps.includes("vision"),
          reasoning: caps.includes("reasoning"),
          tool_use: caps.includes("tool_use"),
        }
      : {};
  return {
    id,
    model_name: id,
    display_name: m.display_name.trim() || null,
    model_type: m.model_type.trim() || "chat",
    context_window: ctx,
    max_output_tokens: m.max_output_tokens > 0 ? m.max_output_tokens : null,
    capabilities: capabilitiesObj,
  };
}

function probePayload(
  apiMode: string,
  apiKey: string,
  apiHost: string,
  apiPath: string,
  authHeaderName: string,
  authHeaderScheme: string,
) {
  const mode = (apiMode.trim() || "openai_compatible") as string;
  return {
    api_mode: mode,
    api_key: apiKey.trim() || null,
    api_key_env: null as string | null,
    api_host: apiHost.trim(),
    api_path: apiPath.trim() || "/chat/completions",
    auth_header_name: authHeaderName.trim() || "Authorization",
    auth_header_scheme: authHeaderScheme,
    network_compatibility: false,
  };
}

const DEFAULT_MEMORY_COMPRESSION_THRESHOLD = "8000";
const DEFAULT_MAX_TOKENS = "4096";

function parsePositiveInteger(value: string): number | null {
  const parsed = Number.parseInt(value.trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

const CAP_LABELS: Record<string, string> = {
  vision: "视觉",
  reasoning: "推理",
  tool_use: "工具调用",
};

function buildModelDesc(m: ModelEntry): string {
  const parts: string[] = [];
  if (m.model_type) parts.push(m.model_type);
  for (const cap of m.capabilities) {
    if (CAP_LABELS[cap]) parts.push(CAP_LABELS[cap]);
  }
  return parts.length > 0 ? parts.join(" · ") : "目录项 · 可配置类型与能力标签";
}

export default function ModelProviderCreatePage() {
  const router = useRouter();

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");


  const [apiMode, setApiMode] = useState("openai_compatible");
  const [apiKey, setApiKey] = useState("");
  const [apiHost, setApiHost] = useState("");
  const [apiPath, setApiPath] = useState("/chat/completions");
  const [authHeaderName, setAuthHeaderName] = useState("Authorization");
  const [authHeaderScheme, setAuthHeaderScheme] = useState("Bearer ");
  const [memoryCompressionThreshold, setMemoryCompressionThreshold] = useState(
    DEFAULT_MEMORY_COMPRESSION_THRESHOLD,
  );
  const [maxTokens, setMaxTokens] = useState(DEFAULT_MAX_TOKENS);

  const [availableModels, setAvailableModels] = useState<ModelEntry[]>([]);
  const [defaultModelName, setDefaultModelName] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogIndex, setDialogIndex] = useState<number | null>(null);
  const [dialogIsNew, setDialogIsNew] = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);

  const clearError = (...keys: string[]) => {
    setErrors((prev) => {
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

  const previewUrl = `${apiHost.trim()}${apiPath.trim() || "/chat/completions"}`;

  const runConnectionCheck = async () => {
    if (!apiHost.trim()) {
      toast.error("请先填写 API 主机");
      return;
    }
    setProbing(true);
    try {
      const { data } = await apiClient.post<{ ok: boolean; message?: string }>(
        "/capabilities/model-providers/check",
        probePayload(apiMode, apiKey, apiHost, apiPath, authHeaderName, authHeaderScheme),
      );
      toast.success(data.message ?? (data.ok ? "连接成功" : "检测完成"));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "检测失败");
    } finally {
      setProbing(false);
    }
  };

  const handleToolbarCheck = () => {
    const empty = availableModels.filter((m) => !m.model_name.trim());
    if (empty.length > 0) {
      toast.error(`有 ${empty.length} 条模型未填写 model_name`);
      return;
    }
    toast.success("模型目录检查通过");
  };

  const handleFetchModels = async () => {
    if (!apiHost.trim()) {
      toast.error("请先填写 API 主机");
      return;
    }
    setProbing(true);
    try {
      const { data } = await apiClient.post<{ models: string[] }>(
        "/capabilities/model-providers/discover-models",
        probePayload(apiMode, apiKey, apiHost, apiPath, authHeaderName, authHeaderScheme),
      );
      const ids = data.models ?? [];
      if (ids.length === 0) {
        toast.info("未发现模型，请检查密钥与地址");
        return;
      }
      setAvailableModels((prev) => {
        const existing = new Set(prev.map((p) => p.model_name.trim()));
        const merged = [...prev];
        for (const id of ids) {
          if (!id || existing.has(id)) continue;
          existing.add(id);
          merged.push({ ...defaultModelEntry(), model_name: id, display_name: id });
        }
        return merged;
      });
      toast.success(`已获取 ${ids.length} 个模型`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "获取失败");
    } finally {
      setProbing(false);
    }
  };

  const handleResetModels = () => {
    setAvailableModels([]);
    setDefaultModelName("");
    toast.info("已重置模型目录");
  };

  const handleAddModel = () => {
    setDialogIndex(null);
    setDialogIsNew(true);
    setDialogOpen(true);
  };

  const openSettings = (index: number) => {
    setDialogIndex(index);
    setDialogIsNew(false);
    setDialogOpen(true);
  };

  const handleDialogSave = (updated: ModelEntry) => {
    if (dialogIsNew && dialogIndex === null) {
      setAvailableModels((prev) => [...prev, updated]);
    } else if (dialogIndex !== null) {
      setAvailableModels((prev) =>
        prev.map((m, i) => (i === dialogIndex ? updated : m)),
      );
    }
    setDialogOpen(false);
    setDialogIsNew(false);
    setDialogIndex(null);
  };

  const handleSave = async () => {
    const next: Record<string, string> = {};
    if (!code.trim()) next.code = "请输入编码";
    if (!name.trim()) next.name = "请输入名称";
    if (!apiHost.trim()) next.api_host = "请输入 API 主机";
    const compressionThreshold = parsePositiveInteger(memoryCompressionThreshold);
    if (compressionThreshold === null) {
      next.memory_compression_threshold = "请输入大于 0 的整数";
    }
    const maxTokensValue = parsePositiveInteger(maxTokens);
    if (maxTokensValue === null) {
      next.max_tokens = "请输入大于 0 的整数";
    }
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }
    setErrors({});

    const catalog = availableModels
      .map(serializeCatalogItem)
      .filter((item) => String(item.id).trim().length > 0);

    setSaving(true);
    try {
      await apiClient.post("/capabilities", {
        type: "model",
        code: code.trim(),
        name: name.trim(),
        description: description.trim() || null,
        status: "active",
        config_json: {
          api_model: apiMode.trim(),
          api_mode: apiMode.trim(),
          api_key: apiKey.trim() || null,
          api_host: apiHost.trim(),
          api_path: apiPath.trim() || "/chat/completions",
          auth_header_name: authHeaderName.trim() || "Authorization",
          auth_header_scheme: authHeaderScheme,
          memory_compression_threshold: compressionThreshold,
          max_tokens: maxTokensValue,
          available_models: catalog,
          ...(defaultModelName.trim() ? { model_name: defaultModelName.trim() } : {}),
        },
      });
      toast.success("新建成功");
      router.push("/admin/models");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="新建模型"
        breadcrumb={[
          { label: "管理中心" },
          { label: "模型管理", href: "/admin/models" },
          { label: "新建" },
        ]}
        actions={
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              className="rounded border border-[#DCDFE6] px-4 py-2 text-[13px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
              onClick={() => router.push("/admin/models")}
            >
              取消
            </button>
            <button
              type="button"
              disabled={probing}
              className="rounded border border-[#DCDFE6] px-3.5 py-2 text-[13px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
              onClick={() => void runConnectionCheck()}
            >
              {probing ? "检测中…" : "检测连接"}
            </button>
            <button
              type="button"
              disabled={saving}
              className="rounded bg-[#409EFF] px-5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#66b1ff] disabled:opacity-50"
              onClick={() => void handleSave()}
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        }
      />

      <div className="rounded-lg border border-[#EBEEF5] bg-white">
        <div className="flex flex-col gap-4 p-6">
          {/* Section 1: 基础信息 */}
          <section className="rounded-[14px] border border-[#EBEEF5] bg-[#F9FAFB] p-4">
            <h2 className="text-[15px] font-semibold text-[#303133]">基础信息</h2>
            <div className="mt-3 flex flex-col gap-3">
              <div className="flex gap-4">
                <FormField label="能力编码 code" required error={errors.code} className="flex-1">
                  <Input
                    value={code}
                    onChange={(e) => {
                      clearError("code");
                      setCode(e.target.value);
                    }}
                    placeholder="openai-prod"
                    className={cn(
                      "h-10 rounded-lg border-[#E4E7ED] text-[13px]",
                      errors.code && "border-red-400",
                    )}
                  />
                </FormField>
                <FormField label="显示名称 name" required error={errors.name} className="flex-1">
                  <Input
                    value={name}
                    onChange={(e) => {
                      clearError("name");
                      setName(e.target.value);
                    }}
                    placeholder="生产 OpenAI"
                    className={cn(
                      "h-10 rounded-lg border-[#E4E7ED] text-[13px]",
                      errors.name && "border-red-400",
                    )}
                  />
                </FormField>
              </div>

              <FormField label="描述 description">
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="用于节点与 Agent 引用时的说明文案"
                  className="h-[72px] resize-none rounded-lg border-[#E4E7ED] px-3 py-2.5 text-[13px]"
                />
              </FormField>

            </div>
          </section>

          {/* Section 2: 连接配置 */}
          <section className="rounded-[14px] border border-[#EBEEF5] bg-[#F9FAFB] p-4">
            <h2 className="text-[15px] font-semibold text-[#303133]">连接配置</h2>
            <div className="mt-3 flex flex-col gap-3">
              <div className="flex gap-4">
                <FormField label="API 模式 api_mode" className="flex-1">
                  <Select
                    value={apiMode}
                    onChange={(e) => setApiMode(e.target.value)}
                    options={[
                      { value: "openai_compatible", label: "openai_compatible（OpenAI API 兼容）" },
                      { value: "deepseek_compatible", label: "deepseek_compatible（DeepSeek API 兼容）" },
                      { value: "openai_responses_compatible", label: "openai_responses_compatible" },
                      { value: "claude_compatible", label: "claude_compatible" },
                      { value: "gemini_compatible", label: "gemini_compatible" },
                    ]}
                    className="h-10 rounded-lg border-[#E4E7ED] text-[13px]"
                  />
                </FormField>
                <FormField label="API 密钥 api_key（可选）" className="flex-1">
                  <Input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="留空则走 api_key_env / 网关鉴权"
                    autoComplete="new-password"
                    className="h-10 rounded-lg border-[#E4E7ED] text-[13px]"
                  />
                </FormField>
              </div>
              <div className="flex gap-4">
                <FormField
                  label="API 主机 api_host"
                  required
                  error={errors.api_host}
                  className="w-[540px] shrink-0"
                >
                  <Input
                    value={apiHost}
                    onChange={(e) => {
                      clearError("api_host");
                      setApiHost(e.target.value);
                    }}
                    placeholder="https://api.openai.com/v1"
                    className={cn(
                      "h-10 rounded-lg border-[#E4E7ED] text-[13px]",
                      errors.api_host && "border-red-400",
                    )}
                  />
                </FormField>
                <FormField label="API 路径 api_path" className="flex-1">
                  <Input
                    value={apiPath}
                    onChange={(e) => setApiPath(e.target.value)}
                    placeholder="/chat/completions"
                    className="h-10 rounded-lg border-[#E4E7ED] text-[13px]"
                  />
                </FormField>
              </div>
              <div className="rounded-[10px] bg-[#F3F8FF] px-3 py-2.5 text-[12px] text-[#606266]">
                当前请求预览：{previewUrl}
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex gap-4">
                  <FormField label="认证请求头 auth_header_name" className="flex-1">
                    <Input
                      value={authHeaderName}
                      onChange={(e) => setAuthHeaderName(e.target.value)}
                      placeholder="Authorization"
                      className="h-10 rounded-lg border-[#E4E7ED] text-[13px]"
                    />
                  </FormField>
                  <FormField label="鉴权值前缀 auth_header_scheme" className="flex-1">
                    <Input
                      value={authHeaderScheme}
                      onChange={(e) => setAuthHeaderScheme(e.target.value)}
                      placeholder="Bearer "
                      className="h-10 rounded-lg border-[#E4E7ED] text-[13px]"
                    />
                  </FormField>
                </div>
                <div className="text-[12px] leading-5 text-[#909399]">
                  默认 <code className="rounded bg-[#F2F6FC] px-1">Authorization: Bearer &lt;key&gt;</code>。
                  网关接入示例：头名填 <code className="rounded bg-[#F2F6FC] px-1">Authorization-Gateway</code>，前缀留空（直接透传 token）。
                </div>
              </div>
              <div className="flex gap-4">
                <FormField
                  label="记忆压缩阈值 memory_compression_threshold"
                  error={errors.memory_compression_threshold}
                  className="w-[360px] shrink-0"
                >
                  <Input
                    type="number"
                    min={1}
                    value={memoryCompressionThreshold}
                    onChange={(e) => {
                      clearError("memory_compression_threshold");
                      setMemoryCompressionThreshold(e.target.value);
                    }}
                    placeholder="8000"
                    className={cn(
                      "h-10 rounded-lg border-[#E4E7ED] text-[13px]",
                      errors.memory_compression_threshold && "border-red-400",
                    )}
                  />
                </FormField>
                <div className="flex flex-1 items-center text-[12px] leading-5 text-[#909399]">
                  Agent 记忆超过该阈值后会压缩旧上下文；上下文较长或工具调用多时可调大到 12000 / 16000。
                </div>
              </div>
              <div className="flex gap-4">
                <FormField
                  label="单次输出上限 max_tokens"
                  error={errors.max_tokens}
                  className="w-[360px] shrink-0"
                >
                  <Input
                    type="number"
                    min={1}
                    value={maxTokens}
                    onChange={(e) => {
                      clearError("max_tokens");
                      setMaxTokens(e.target.value);
                    }}
                    placeholder="4096"
                    className={cn(
                      "h-10 rounded-lg border-[#E4E7ED] text-[13px]",
                      errors.max_tokens && "border-red-400",
                    )}
                  />
                </FormField>
                <div className="flex flex-1 items-center text-[12px] leading-5 text-[#909399]">
                  单次 LLM 调用最多输出多少 token。留默认 4096 适合短回复；生成 SQL / 代码 / 报告等长输出建议 8192 或 16384，否则会在中途被截断。
                </div>
              </div>
            </div>
          </section>

          {/* Section 3: 模型目录 */}
          <section className="rounded-[14px] border border-[#D9ECFF] bg-[#F3F8FF] p-4">
            <h2 className="text-[15px] font-semibold text-[#303133]">
              模型目录 available_models
            </h2>
            <p className="mt-1 text-[12px] text-[#909399]">
              检查 / 获取 / 重置 / 新建模型；右侧选择默认 model_name
            </p>

            <div className="mt-3.5 flex items-center gap-2">
              <button
                type="button"
                className="rounded border border-[#DCDFE6] bg-white px-3 py-1.5 text-[12px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
                onClick={handleToolbarCheck}
              >
                检查
              </button>
              <button
                type="button"
                disabled={probing}
                className="rounded border border-[#DCDFE6] bg-white px-3 py-1.5 text-[12px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
                onClick={() => void handleFetchModels()}
              >
                获取
              </button>
              <button
                type="button"
                className="rounded border border-[#DCDFE6] bg-white px-3 py-1.5 text-[12px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
                onClick={handleResetModels}
              >
                重置
              </button>
              <button
                type="button"
                className="rounded bg-[#409EFF] px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-[#66b1ff]"
                onClick={handleAddModel}
              >
                + 新建模型
              </button>
            </div>

            <div className="mt-4 rounded-xl border border-[#EBEEF5] bg-white p-3">
              {availableModels.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-[13px] text-[#909399]">
                  暂无模型，点击「+ 新建模型」或「获取」添加
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2.5">
                  {availableModels.map((m, index) => {
                    const isDefault =
                      defaultModelName.trim() !== "" &&
                      m.model_name.trim() === defaultModelName.trim();
                    const trimmedName = m.model_name.trim();
                    return (
                      <div
                        key={index}
                        className={cn(
                          "flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2.5 transition-colors",
                          isDefault
                            ? "border-[#B3D8FF] bg-[#F0F9FF]"
                            : "border-[#EBEEF5] bg-white hover:border-[#C0C4CC]",
                        )}
                        onClick={() => {
                          if (!trimmedName) return;
                          setDefaultModelName(isDefault ? "" : trimmedName);
                        }}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-[13px] font-semibold text-[#303133]">
                              {trimmedName || "（未命名）"}
                            </span>
                            {isDefault && (
                              <span className="shrink-0 text-[10px] font-medium text-[#409EFF]">
                                默认
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 truncate text-[11px] text-[#909399]">
                            {buildModelDesc(m)}
                          </p>
                        </div>
                        <div className="ml-2 flex shrink-0 items-center gap-1.5">
                          <button
                            type="button"
                            className={cn(
                              "flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors",
                              isDefault
                                ? "border-[#409EFF] text-[#409EFF] hover:bg-[#ECF5FF]"
                                : "border-[#DCDFE6] text-[#606266] hover:border-[#409EFF] hover:text-[#409EFF]",
                            )}
                            onClick={(e) => {
                              e.stopPropagation();
                              openSettings(index);
                            }}
                          >
                            <Settings2 className="size-3" />
                            设置
                          </button>
                          <button
                            type="button"
                            className="flex items-center rounded border border-transparent p-1 text-[#C0C4CC] transition-colors hover:border-[#FFCDD2] hover:text-[#F56C6C]"
                            onClick={(e) => {
                              e.stopPropagation();
                              setAvailableModels((prev) => prev.filter((_, i) => i !== index));
                              if (isDefault) setDefaultModelName("");
                            }}
                          >
                            <X className="size-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      <ModelItemDialog
        open={dialogOpen}
        entry={
          dialogIndex !== null && availableModels[dialogIndex]
            ? availableModels[dialogIndex]
            : defaultModelEntry()
        }
        isNew={dialogIsNew}
        onSave={handleDialogSave}
        onCancel={() => {
          setDialogOpen(false);
          setDialogIsNew(false);
          setDialogIndex(null);
        }}
      />
    </div>
  );
}
