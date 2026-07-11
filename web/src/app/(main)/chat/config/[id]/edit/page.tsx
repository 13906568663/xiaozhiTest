"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { MultiSelect } from "@/components/ui/multi-select";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useFormErrors } from "@/hooks/use-form-errors";

type Capability = {
  id: string;
  code: string;
  name: string;
  type: string;
  description: string | null;
  config_json: Record<string, unknown>;
};

type KnowledgeBaseItem = {
  id: string;
  code: string;
  name: string;
  description?: string | null;
};

type SkillOption = {
  id: string;
  code: string;
  description: string | null;
  status: string;
};

type ChatbotDetail = {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  icon?: string;
  model_binding: Record<string, unknown>;
  mcp_bindings: Array<{ ref?: string; [k: string]: unknown }>;
  function_bindings: Array<{ ref?: string; [k: string]: unknown }>;
  knowledge_bindings: Array<{ ref?: string; [k: string]: unknown }>;
  skill_bindings?: string[];
  max_turns: number;
  status?: "active" | "inactive";
  session_count?: number;
};

const ICON_STYLES = [
  { icon: "🤖", bg: "#E8F3FF", label: "机器人" },
  { icon: "🔍", bg: "#FFF3E0", label: "搜索" },
  { icon: "💬", bg: "#F3E8FF", label: "对话" },
  { icon: "⭐", bg: "#FFE8E8", label: "星标" },
];

function extractAvailableModels(config: Record<string, unknown>): string[] {
  const raw = config.available_models;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) =>
    typeof item === "string"
      ? item
      : String((item as Record<string, unknown>).id ?? (item as Record<string, unknown>).model ?? ""),
  ).filter(Boolean);
}

export default function ChatbotEditPage() {
  const router = useRouter();
  const params = useParams();
  const botId = params.id as string;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { errors, setErrors, clearErrors } = useFormErrors();

  const [form, setForm] = useState({
    name: "",
    description: "",
    system_prompt: "",
    icon: "🤖",
    model_ref: "",
    model_name: "",
    max_turns: 50,
    enabled: true,
  });

  const [models, setModels] = useState<Capability[]>([]);
  const [mcps, setMcps] = useState<Capability[]>([]);
  const [functions, setFunctions] = useState<Capability[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseItem[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);

  const [selectedMcpRefs, setSelectedMcpRefs] = useState<string[]>([]);
  const [selectedFuncRefs, setSelectedFuncRefs] = useState<string[]>([]);
  const [selectedKbRefs, setSelectedKbRefs] = useState<string[]>([]);
  const [selectedSkillCodes, setSelectedSkillCodes] = useState<string[]>([]);
  const [sessionCount, setSessionCount] = useState(0);
  const [deactivateConfirmOpen, setDeactivateConfirmOpen] = useState(false);

  const set = (key: string, val: string | boolean | number) => {
    clearErrors(key);
    setForm((f) => ({ ...f, [key]: val }));
  };

  const validate = () => {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "请输入机器人名称";
    if (form.max_turns < 1 || form.max_turns > 1000) next.max_turns = "对话轮次需在 1 ~ 1000 之间";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [botRes, capsRes, kbRes, skillsRes] = await Promise.allSettled([
        apiClient.get<ChatbotDetail>(`/chatbots/${botId}`),
        apiClient.get<Capability[]>("/capabilities"),
        apiClient.get<KnowledgeBaseItem[]>("/knowledge-bases"),
        apiClient.get<{ items: SkillOption[]; total: number }>("/skills", {
          params: { status: "active", page: 1, page_size: 200 },
        }),
      ]);

      if (capsRes.status === "fulfilled" && Array.isArray(capsRes.value.data)) {
        const caps = capsRes.value.data;
        setModels(caps.filter((c) => c.type === "model"));
        setMcps(caps.filter((c) => c.type === "mcp" || c.type === "virtual_mcp"));
        setFunctions(caps.filter((c) => c.type === "function"));
      }
      if (kbRes.status === "fulfilled" && Array.isArray(kbRes.value.data)) {
        setKnowledgeBases(kbRes.value.data);
      }
      if (skillsRes.status === "fulfilled" && Array.isArray(skillsRes.value.data?.items)) {
        setSkills(skillsRes.value.data.items);
      }

      if (botRes.status === "fulfilled") {
        const bot = botRes.value.data;
        const binding = bot.model_binding as { ref?: string; config?: Record<string, unknown> };
        setForm({
          name: bot.name || "",
          description: bot.description || "",
          system_prompt: bot.system_prompt || "",
          icon: bot.icon || "🤖",
          model_ref: binding?.ref || "",
          model_name: String(binding?.config?.model_name ?? ""),
          max_turns: bot.max_turns || 50,
          enabled: bot.status !== "inactive",
        });
        setSelectedMcpRefs(bot.mcp_bindings.map((b) => b.ref ?? "").filter(Boolean));
        setSelectedFuncRefs(bot.function_bindings.map((b) => b.ref ?? "").filter(Boolean));
        setSelectedKbRefs(bot.knowledge_bindings.map((b) => b.ref ?? "").filter(Boolean));
        setSelectedSkillCodes(
          Array.isArray(bot.skill_bindings)
            ? bot.skill_bindings.filter((c): c is string => typeof c === "string" && c.length > 0)
            : [],
        );
        setSessionCount(typeof bot.session_count === "number" ? bot.session_count : 0);
      } else {
        toast.error("加载机器人信息失败");
      }
    } catch {
      toast.error("加载失败");
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const selectedModelProvider = models.find((m) => m.code === form.model_ref);
  const availableModels = selectedModelProvider
    ? extractAvailableModels(selectedModelProvider.config_json)
    : [];

  const handleEnabledChange = (next: boolean) => {
    if (!next && form.enabled) {
      if (sessionCount > 0) {
        setDeactivateConfirmOpen(true);
        return;
      }
    }
    set("enabled", next);
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      await apiClient.put(`/chatbots/${botId}`, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        system_prompt: form.system_prompt.trim(),
        icon: form.icon,
        model_binding: form.model_ref
          ? {
              source: "global",
              ref: form.model_ref,
              config: form.model_name ? { model_name: form.model_name } : {},
            }
          : {},
        mcp_bindings: selectedMcpRefs.map((ref) => ({ source: "global", ref, config: {} })),
        function_bindings: selectedFuncRefs.map((ref) => ({ source: "global", ref, config: {} })),
        knowledge_bindings: selectedKbRefs.map((ref) => ({ source: "global", ref, config: { inject_mode: "tool" } })),
        skill_bindings: selectedSkillCodes,
        max_turns: form.max_turns,
        status: form.enabled ? "active" : "inactive",
      });
      toast.success("保存成功");
      router.push("/chat/config");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-sm text-[var(--el-text-secondary)]">
        加载中…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="编辑机器人"
        breadcrumb={[{ label: "对话配置" }, { label: "编辑机器人" }]}
        actions={
          <div className="flex items-center gap-2.5">
            <Button variant="secondary" onClick={() => router.push("/chat/config")}>
              取消
            </Button>
            <Button variant="primary" disabled={saving} onClick={() => void handleSave()}>
              {saving ? "保存中…" : "保存配置"}
            </Button>
          </div>
        }
      />

      <div className="flex gap-4">
        {/* 左列 */}
        <div className="flex flex-1 flex-col gap-4">
          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-4 text-sm font-semibold text-[var(--el-text-primary)]">基本信息</h3>
            <div className="flex flex-col gap-4">
              <FormField label="机器人名称" required error={errors.name}>
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="请输入名称" />
              </FormField>
              <FormField label="描述">
                <Textarea className="min-h-[80px]" value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="请填写描述" />
              </FormField>
              <div className="flex gap-4">
                <FormField label="最大对话轮次" className="w-40" error={errors.max_turns}>
                  <Input type="number" min={1} max={1000} value={String(form.max_turns)} onChange={(e) => set("max_turns", parseInt(e.target.value) || 50)} />
                </FormField>
                <FormField label="头像风格" className="flex-1">
                  <div className="flex items-center gap-2.5">
                    {ICON_STYLES.map((item) => (
                      <button key={item.icon} type="button" className={cn("flex size-10 items-center justify-center rounded-lg border text-xl transition-colors", form.icon === item.icon ? "border-2 border-[var(--el-primary)]" : "border-[var(--el-border-lighter)] hover:border-[var(--el-primary)]")} style={{ backgroundColor: item.bg }} onClick={() => set("icon", item.icon)} title={item.label}>
                        {item.icon}
                      </button>
                    ))}
                  </div>
                </FormField>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-1 text-sm font-semibold text-[var(--el-text-primary)]">系统提示词</h3>
            <p className="mb-3 text-xs text-[var(--el-text-placeholder)]">定义机器人角色、行为和回复风格。</p>
            <Textarea className="min-h-[240px] bg-[#F9F9F9]" value={form.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} placeholder="请填写系统提示词" />
            <p className="mt-1.5 text-right text-[11px] text-[var(--el-text-placeholder)]">已输入 {form.system_prompt.length} / 2000</p>
          </section>
        </div>

        {/* 右列 */}
        <div className="flex flex-1 flex-col gap-4">
          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-4 text-sm font-semibold text-[var(--el-text-primary)]">模型配置</h3>
            <div className="flex flex-col gap-4">
              <FormField label="模型提供方">
                {models.length > 0 ? (
                  <Select
                    value={form.model_ref}
                    onChange={(e) => {
                      const ref = e.target.value;
                      const provider = models.find((m) => m.code === ref);
                      const defModel = provider ? String(provider.config_json.model_name ?? "") || extractAvailableModels(provider.config_json)[0] || "" : "";
                      setForm((f) => ({ ...f, model_ref: ref, model_name: defModel }));
                    }}
                    options={[{ value: "", label: "暂不指定" }, ...models.map((m) => ({ value: m.code, label: m.name }))]}
                  />
                ) : (
                  <p className="rounded-lg border border-dashed border-[var(--el-border-lighter)] bg-[#F8FAFF] px-4 py-3 text-sm text-[var(--el-text-secondary)]">暂无可用模型</p>
                )}
              </FormField>
              {form.model_ref && (
                <FormField label="模型">
                  {availableModels.length > 0 ? (
                    <Select value={form.model_name} onChange={(e) => set("model_name", e.target.value)} options={[{ value: "", label: "使用默认" }, ...availableModels.map((m) => ({ value: m, label: m }))]} />
                  ) : (
                    <Input value={form.model_name} onChange={(e) => set("model_name", e.target.value)} placeholder="输入模型名称" />
                  )}
                </FormField>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-1 text-sm font-semibold text-[var(--el-text-primary)]">MCP / 工具绑定</h3>
            <p className="mb-3 text-xs text-[var(--el-text-placeholder)]">选择机器人可调用的工具。</p>
            <div className="flex flex-col gap-4">
              {mcps.length > 0 && (
                <FormField label="MCP 工具">
                  <MultiSelect
                    value={selectedMcpRefs}
                    onChange={setSelectedMcpRefs}
                    options={mcps.map((c) => ({ value: c.code, label: c.name }))}
                    placeholder="选择 MCP 工具"
                  />
                </FormField>
              )}
              {functions.length > 0 && (
                <FormField label="HTTP 函数">
                  <MultiSelect
                    value={selectedFuncRefs}
                    onChange={setSelectedFuncRefs}
                    options={functions.map((c) => ({ value: c.code, label: c.name }))}
                    placeholder="选择 HTTP 函数"
                  />
                </FormField>
              )}
              {mcps.length === 0 && functions.length === 0 && (
                <p className="rounded-lg border border-dashed border-[var(--el-border-lighter)] bg-[#F8FAFF] px-4 py-3 text-sm text-[var(--el-text-secondary)]">暂无可用工具</p>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-1 text-sm font-semibold text-[var(--el-text-primary)]">知识库绑定</h3>
            <p className="mb-3 text-xs text-[var(--el-text-placeholder)]">给机器人补充检索式知识来源。</p>
            {knowledgeBases.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--el-border-lighter)] bg-[#F8FAFF] px-4 py-3 text-sm text-[var(--el-text-secondary)]">暂无知识库</p>
            ) : (
              <MultiSelect
                value={selectedKbRefs}
                onChange={setSelectedKbRefs}
                options={knowledgeBases.map((kb) => ({ value: kb.code, label: kb.name }))}
                placeholder="选择知识库"
              />
            )}
          </section>

          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-1 text-sm font-semibold text-[var(--el-text-primary)]">技能绑定（SKILL.md）</h3>
            <p className="mb-3 text-xs text-[var(--el-text-placeholder)]">
              选中的技能（SKILL.md）会以 <code>&lt;available_skills&gt;</code> 索引追加到 system_prompt，仅展示每条 <code>code</code> 与 <code>description</code>。模型识别到任务匹配某条技能时，主动调用 <code>load_skill(code)</code> 工具按需加载其正文执行，未触发的技能正文不会进入上下文，节省 token。
            </p>
            {skills.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--el-border-lighter)] bg-[#F8FAFF] px-4 py-3 text-sm text-[var(--el-text-secondary)]">暂无可用技能，请先到「技能管理」页面创建并启用 SKILL.md。</p>
            ) : (
              <MultiSelect
                value={selectedSkillCodes}
                onChange={setSelectedSkillCodes}
                options={skills.map((s) => ({
                  value: s.code,
                  label: s.description ? `${s.code} — ${s.description}` : s.code,
                }))}
                placeholder="选择技能"
              />
            )}
          </section>

          <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-[var(--el-text-primary)]">状态设置</h3>
            <div className="flex items-center justify-between">
              <div className="min-w-0 pr-3">
                <span className="text-[13px] text-[var(--el-text-regular)]">启用机器人</span>
                {sessionCount > 0 && form.enabled ? (
                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--el-text-placeholder)]">
                    当前共有 {sessionCount} 个历史会话；关闭启用时若存在会话将先请您确认，避免误操作。
                  </p>
                ) : null}
              </div>
              <ToggleSwitch checked={form.enabled} onChange={handleEnabledChange} />
            </div>
          </section>
        </div>
      </div>

      <ConfirmDialog
        open={deactivateConfirmOpen}
        title="确认停用机器人？"
        message={`该机器人已有 ${sessionCount} 个会话记录。停用后无法在对话台新建会话、分叉分支或继续发送新消息（列表「对话」入口将不可用），历史记录仍保留。确定停用吗？`}
        confirmText="停用"
        variant="warning"
        onConfirm={() => {
          set("enabled", false);
          setDeactivateConfirmOpen(false);
        }}
        onCancel={() => setDeactivateConfirmOpen(false)}
      />
    </div>
  );
}

