"use client";

import { useEffect, useState } from "react";

import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { useFormErrors } from "@/hooks/use-form-errors";

export type ModelEntry = {
  model_name: string;
  display_name: string;
  model_type: string;
  context_window: string;
  max_output_tokens: number;
  capabilities: string[];
};

export const defaultModelEntry = (): ModelEntry => ({
  model_name: "",
  display_name: "",
  model_type: "chat",
  context_window: "128k",
  max_output_tokens: 4096,
  capabilities: [],
});

type ModelItemDialogProps = {
  open: boolean;
  entry: ModelEntry;
  isNew?: boolean;
  onSave: (entry: ModelEntry) => void;
  onCancel: () => void;
};

const CAPABILITY_OPTIONS = [
  { key: "vision", label: "视觉" },
  { key: "reasoning", label: "推理" },
  { key: "tool_use", label: "工具" },
];

const MODEL_TYPE_OPTIONS = [
  { value: "chat", label: "chat · 聊天" },
  { value: "embedding", label: "embedding · 嵌入" },
  { value: "completion", label: "completion · 补全" },
  { value: "image", label: "image · 图像" },
  { value: "audio", label: "audio · 音频" },
];

export function ModelItemDialog({ open, entry, isNew, onSave, onCancel }: ModelItemDialogProps) {
  const [draft, setDraft] = useState<ModelEntry>({ ...entry });
  const { errors: fieldErrors, setErrors: setFieldErrors, clearErrors: clearFieldErrors } = useFormErrors();

  useEffect(() => {
    if (open) {
      setDraft({ ...entry });
      setFieldErrors({});
    }
  }, [open, entry, setFieldErrors]);

  if (!open) return null;

  const set = <K extends keyof ModelEntry>(key: K, value: ModelEntry[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const trySave = () => {
    const next: Record<string, string> = {};
    if (!draft.model_name.trim()) next.model_name = "请输入模型 ID（model_name）";
    if (!draft.display_name.trim()) next.display_name = "请输入显示名称";
    if (Object.keys(next).length > 0) {
      setFieldErrors(next);
      toast.error("请填写模型 ID 与显示名称");
      return;
    }
    setFieldErrors({});
    onSave(draft);
  };

  const toggleCapability = (cap: string) => {
    setDraft((d) => ({
      ...d,
      capabilities: d.capabilities.includes(cap)
        ? d.capabilities.filter((c) => c !== cap)
        : [...d.capabilities, cap],
    }));
  };

  const inputClass = "h-9 rounded-lg border-[#E4E7ED] text-[13px]";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/18" onClick={onCancel} aria-hidden />
      <div
        className="relative z-10 flex w-[420px] flex-col rounded-xl border border-[#EBEEF5] bg-white shadow-[0_12px_32px_rgba(0,0,0,0.09)]"
        role="dialog"
        aria-modal="true"
      >
        <div className="border-b border-[#EBEEF5] px-5 pb-4 pt-5">
          <h2 className="text-[17px] font-semibold text-[#303133]">编辑模型目录项</h2>
          <p className="mt-1.5 text-[11px] text-[#909399]">
            对应 web ProviderModelItem / ModelEditorState
          </p>
        </div>

        <div className="flex flex-col gap-3.5 px-5 py-5">
          <FormField
            label={`模型 ID · id${isNew ? "" : "（只读）"}`}
            required={isNew}
            error={fieldErrors.model_name}
          >
            {isNew ? (
              <Input
                value={draft.model_name}
                onChange={(e) => {
                  clearFieldErrors("model_name");
                  set("model_name", e.target.value);
                }}
                className={cn(inputClass, fieldErrors.model_name && "border-red-400")}
                placeholder="如 gpt-4o"
              />
            ) : (
              <div
                className={cn(
                  "flex h-9 items-center rounded-lg border bg-[#F5F7FA] px-3 text-[13px] text-[#909399]",
                  fieldErrors.model_name ? "border-red-400" : "border-[#E4E7ED]",
                )}
              >
                {draft.model_name || "—"}
              </div>
            )}
          </FormField>

          <FormField label="显示名称 · displayName" required error={fieldErrors.display_name}>
            <Input
              value={draft.display_name}
              onChange={(e) => {
                clearFieldErrors("display_name");
                set("display_name", e.target.value);
              }}
              className={cn(inputClass, fieldErrors.display_name && "border-red-400")}
              placeholder="如 GPT-4o"
            />
          </FormField>

          <FormField label="类型 · modelType">
            <Select
              value={draft.model_type}
              onChange={(e) => set("model_type", e.target.value)}
              options={MODEL_TYPE_OPTIONS}
              className="h-9 rounded-lg border-[#E4E7ED] text-[13px]"
            />
          </FormField>

          <FormField label="能力 capabilityVision / Reasoning / ToolUse">
            <div className="flex flex-wrap gap-3">
              {CAPABILITY_OPTIONS.map((cap) => {
                const active = draft.capabilities.includes(cap.key);
                return (
                  <button
                    key={cap.key}
                    type="button"
                    onClick={() => toggleCapability(cap.key)}
                    className={cn(
                      "rounded-md border px-2.5 py-1.5 text-[12px] transition-colors",
                      active
                        ? "border-[#B3D8FF] bg-[#ECF5FF] text-[#409EFF]"
                        : "border-[#E4E7ED] bg-white text-[#909399]",
                    )}
                  >
                    {cap.label}{active && " ✓"}
                  </button>
                );
              })}
            </div>
          </FormField>

          <FormField label="上下文窗口 · contextWindow">
            <Input
              value={draft.context_window}
              onChange={(e) => set("context_window", e.target.value)}
              className={inputClass}
              placeholder="如 128k"
            />
          </FormField>

          <FormField label="最大输出 · maxOutputTokens">
            <Input
              type="number"
              value={draft.max_output_tokens}
              onChange={(e) => set("max_output_tokens", Number(e.target.value) || 0)}
              className={inputClass}
              placeholder="如 16384"
            />
          </FormField>

          <p className="text-[10px] leading-relaxed text-[#C0C4CC]">
            保存后写回 Provider 的 available_models JSON；与 capability-manager
            中「新建模型 / 编辑模型」弹层字段一致。
          </p>
        </div>

        <div className="flex items-center justify-end gap-2.5 border-t border-[#EBEEF5] px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-[#DCDFE6] px-[18px] py-2 text-[13px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={trySave}
            className="rounded bg-[#409EFF] px-[22px] py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#66b1ff]"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
