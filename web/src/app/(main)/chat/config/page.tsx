"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, ChevronDown } from "lucide-react";

import { apiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/types";
import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

type ChatbotRecord = {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  model_binding: Record<string, unknown>;
  mcp_bindings: Record<string, unknown>[];
  function_bindings: Record<string, unknown>[];
  knowledge_bindings: Record<string, unknown>[];
  max_turns: number;
  session_count: number;
  icon?: string;
  status?: "active" | "inactive";
  created_at: string;
  updated_at: string;
};

const AVATAR_COLORS: Record<string, string> = {
  "🤖": "#E8F3FF",
  "🛠️": "#E8F9F0",
  "🔍": "#FFF3E0",
  "💬": "#F3E8FF",
  "⭐": "#FFE8E8",
};

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
];

function effectiveStatus(bot: ChatbotRecord): "active" | "inactive" {
  return bot.status === "inactive" ? "inactive" : "active";
}

function extractModelName(binding: Record<string, unknown>): string {
  const config = binding.config as Record<string, unknown> | undefined;
  if (config?.model_name) return String(config.model_name);
  const ref = binding.ref as string | undefined;
  return ref || "—";
}

export default function ChatConfigPage() {
  const router = useRouter();
  const [items, setItems] = useState<ChatbotRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<ChatbotRecord[]>("/chatbots");
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e instanceof ApiError) toast.error(e.message);
      else toast.error("加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const filtered = useMemo(() => {
    let list = items;
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (b) =>
          b.name.toLowerCase().includes(q) ||
          (b.description && b.description.toLowerCase().includes(q)),
      );
    }
    if (statusFilter === "active") {
      list = list.filter((b) => effectiveStatus(b) === "active");
    } else if (statusFilter === "inactive") {
      list = list.filter((b) => effectiveStatus(b) === "inactive");
    }
    return list;
  }, [items, searchQuery, statusFilter]);

  const handleDelete = async () => {
    if (!confirmTarget) return;
    try {
      await apiClient.delete(`/chatbots/${confirmTarget.id}`);
      setConfirmTarget(null);
      await loadList();
    } catch (e) {
      if (e instanceof ApiError) toast.error(e.message);
      else toast.error("删除失败");
    }
  };

  return (
    <div className="flex flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="对话配置"
        description="管理智能对话机器人，配置模型、提示词和工具，实现灵活的多场景对话服务。"
        breadcrumb={[{ label: "对话中心" }, { label: "对话配置" }]}
        actions={
          <Button variant="primary" onClick={() => router.push("/chat/config/create")}>
            新建机器人
          </Button>
        }
      />

      {/* 搜索 + 筛选 */}
      <div className="flex items-center gap-3">
        <div className="relative w-[300px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--el-text-placeholder)]" />
          <input
            type="text"
            className="h-9 w-full rounded-md border border-[var(--el-border-base)] bg-white pl-9 pr-3 text-[13px] text-[var(--el-text-primary)] outline-none placeholder:text-[var(--el-text-placeholder)] focus:border-[var(--el-primary)]"
            placeholder="搜索机器人名称..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="relative">
          <select
            className="h-9 w-[130px] appearance-none rounded-md border border-[var(--el-border-base)] bg-white px-3 pr-8 text-[13px] text-[var(--el-text-regular)] outline-none focus:border-[var(--el-primary)]"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[var(--el-text-secondary)]" />
        </div>
      </div>

      {/* 卡片列表 */}
      {loading && <p className="text-sm text-[var(--el-text-secondary)]">加载中…</p>}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-[var(--el-text-placeholder)]">暂无数据</p>
      )}
      {!loading && filtered.length > 0 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          {filtered.map((bot) => (
            <ChatbotCard
              key={bot.id}
              bot={bot}
              onEdit={() => router.push(`/chat/config/${bot.id}/edit`)}
              onDelete={() => setConfirmTarget({ id: bot.id, name: bot.name })}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认删除"
        message={`确定删除「${confirmTarget?.name}」？此操作不可恢复。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}

function ChatbotCard({
  bot,
  onEdit,
  onDelete,
}: {
  bot: ChatbotRecord;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const status = effectiveStatus(bot);
  const icon = bot.icon || "🤖";
  const avatarBg = AVATAR_COLORS[icon] || "#E8F3FF";
  const modelName = extractModelName(bot.model_binding);
  const toolCount = bot.mcp_bindings.length + bot.function_bindings.length;

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-[var(--el-border-lighter)] bg-white">
      {/* 上半：头像 + 信息 */}
      <div className="flex gap-3 border-b border-[#F0F2F5] px-4 pb-3 pt-4">
        <div
          className="flex size-[46px] shrink-0 items-center justify-center rounded-[10px] text-[22px]"
          style={{ backgroundColor: avatarBg }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-[15px] font-semibold text-[var(--el-text-primary)]">
                {bot.name}
              </span>
            </div>
            <span
              className={cn(
                "shrink-0 rounded px-2 py-0.5 text-[11px]",
                status === "active"
                  ? "bg-[#F0F9EB] text-[#67C23A]"
                  : "bg-[#F4F4F5] text-[var(--el-text-secondary)]",
              )}
            >
              {status === "active" ? "● 启用" : "○ 停用"}
            </span>
          </div>
          <p className="line-clamp-2 min-h-[42px] text-[13px] leading-relaxed text-[var(--el-text-regular)]">
            {bot.description || "暂无描述"}
          </p>
          <div className="flex items-center gap-1 text-xs">
            <span className="text-[var(--el-text-secondary)]">模型:</span>
            <span className={status === "active" ? "text-[var(--el-primary)]" : "text-[var(--el-text-secondary)]"}>
              {modelName}
            </span>
          </div>
        </div>
      </div>

      {/* 下半：统计 + 操作 */}
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-3.5 text-xs text-[var(--el-text-secondary)]">
          <span>{bot.session_count} 会话</span>
          <span>最大 {bot.max_turns} 轮</span>
          {toolCount > 0 && <span>{toolCount} 项工具</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {status === "active" ? (
            <a
              href={withBasePath(`/chat-console/${bot.id}`)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center rounded border border-[#BFDBFE] bg-[#EFF6FF] px-2.5 py-1 text-xs font-semibold text-[#2563EB] no-underline"
            >
              对话
            </a>
          ) : (
            <span
              className="inline-flex cursor-not-allowed items-center rounded border border-[var(--el-border-lighter)] bg-[#F5F7FA] px-2.5 py-1 text-xs font-medium text-[var(--el-text-placeholder)]"
              title="机器人已停用，请编辑并启用后再打开对话台"
            >
              对话
            </span>
          )}
          <button
            className="rounded border border-[var(--el-border-base)] bg-white px-2.5 py-1 text-xs text-[var(--el-text-regular)]"
            onClick={onEdit}
          >
            编辑
          </button>
          <button
            className="rounded border border-[#FFCCC7] bg-[#FFF1F0] px-2.5 py-1 text-xs font-medium text-[#F04438]"
            onClick={onDelete}
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}
