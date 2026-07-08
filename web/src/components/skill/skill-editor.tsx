"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Sparkles } from "lucide-react";

import { Textarea } from "@/components/ui/textarea";
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { cn } from "@/lib/utils";

import {
  DEFAULT_SKILL_TEMPLATE,
  parseSkillFrontmatter,
} from "./skill-frontmatter";

export type SkillEditorValue = {
  source: string;
  status: "active" | "inactive";
};

export function SkillEditor({
  initial,
  onChange,
}: {
  initial: SkillEditorValue;
  onChange: (value: SkillEditorValue) => void;
}) {
  const [source, setSource] = useState(initial.source);
  const [status, setStatus] = useState<"active" | "inactive">(initial.status);

  useEffect(() => {
    onChange({ source, status });
  }, [source, status, onChange]);

  const parsed = useMemo(() => parseSkillFrontmatter(source), [source]);
  const bodyLength = parsed.ok ? parsed.body.length : 0;
  const bodyLines = parsed.ok ? parsed.body.split(/\r?\n/).length : 0;

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
      {/* 左栏：SKILL.md 编辑区 */}
      <div className="flex flex-col gap-3 rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--el-text-primary)]">
            <Sparkles className="size-4 text-[var(--el-primary)]" />
            SKILL.md 文档
          </h3>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSource(DEFAULT_SKILL_TEMPLATE)}
              className="text-xs text-[var(--el-primary)] hover:underline"
            >
              恢复为模板
            </button>
          </div>
        </div>
        <p className="text-[11px] text-[var(--el-text-placeholder)]">
          标准格式：以 <code>---</code> 包裹 YAML frontmatter（必填 name / description），
          后接 markdown 正文。运行时会把正文拼接到挂载该技能的节点 prompt 末尾。
        </p>
        <Textarea
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder={DEFAULT_SKILL_TEMPLATE}
          className="min-h-[480px] font-mono text-xs leading-6"
        />
      </div>

      {/* 右栏：实时解析预览 + 状态开关 */}
      <div className="flex flex-col gap-4">
        <div className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <h3 className="mb-3 text-sm font-semibold text-[var(--el-text-primary)]">
            解析预览
          </h3>

          {!parsed.ok && (
            <div className="flex items-start gap-2 rounded-md border border-[var(--el-danger-light-5)] bg-[var(--el-danger-light-9)] px-3 py-2 text-xs text-[var(--el-danger)]">
              <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
              <span>{parsed.error}</span>
            </div>
          )}

          {parsed.ok && (
            <div className="flex flex-col gap-3 text-xs">
              <PreviewRow
                label="name"
                value={parsed.meta.name ?? ""}
                valid={!!parsed.meta.name}
                placeholder="（未填写）"
                mono
              />
              <PreviewRow
                label="description"
                value={parsed.meta.description ?? ""}
                valid={!!parsed.meta.description}
                placeholder="（未填写）"
              />

              <div className="grid grid-cols-2 gap-2">
                <Stat label="正文字数" value={String(bodyLength)} />
                <Stat label="正文行数" value={String(bodyLines)} />
              </div>

              {parsed.issues.length > 0 && (
                <div className="rounded-md border border-[var(--el-warning-light-5)] bg-[var(--el-warning-light-9)] px-3 py-2 text-[11px] text-[var(--el-warning)]">
                  <div className="mb-1 font-semibold">需要注意：</div>
                  <ul className="list-disc space-y-0.5 pl-4">
                    {parsed.issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}

              {parsed.issues.length === 0 && parsed.meta.name && (
                <div className="flex items-center gap-1.5 text-[11px] text-[var(--el-success)]">
                  <CheckCircle2 className="size-3.5" />
                  frontmatter 格式正常
                </div>
              )}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <h3 className="mb-3 text-sm font-semibold text-[var(--el-text-primary)]">
            状态
          </h3>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] text-[var(--el-text-regular)]">
                {status === "active" ? "已启用" : "已停用"}
              </p>
              <p className="mt-1 text-[11px] text-[var(--el-text-placeholder)]">
                停用后模板节点引用此技能时不会注入其正文。
              </p>
            </div>
            <ToggleSwitch
              checked={status === "active"}
              onChange={(v) => setStatus(v ? "active" : "inactive")}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviewRow({
  label,
  value,
  valid,
  placeholder,
  mono = false,
}: {
  label: string;
  value: string;
  valid: boolean;
  placeholder: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-[var(--el-text-placeholder)]">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 break-words text-xs",
          mono && "font-mono",
          valid ? "text-[var(--el-text-primary)]" : "italic text-[var(--el-text-placeholder)]",
        )}
      >
        {valid ? value : placeholder}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--el-border-lighter)] bg-[var(--el-bg-page)] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[var(--el-text-placeholder)]">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--el-text-primary)]">
        {value}
      </div>
    </div>
  );
}
