"use client";

import {
  Children,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Copy,
  Download,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Network,
  Paperclip,
  PencilLine,
  RefreshCcw,
  Send,
  Square,
  Table2,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  X,
} from "lucide-react";
import rehypeKatex from "rehype-katex";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  extractChatPlanFromToolCalls,
  type ChatAgentAction,
  type ChatPlanPayload,
  type ChatPlanState,
} from "@/lib/chat-stream";
import { cn } from "@/lib/utils";

export type ChatMessageItem = {
  id: string;
  role: string;
  content: string;
  seq: number;
  created_at: string;
  tool_calls_json?: Array<Record<string, unknown>>;
  plan?: ChatPlanPayload;
  actions?: ChatAgentAction[];
  thinking?: string;
  localOnly?: boolean;
  generationState?: "streaming" | "stopped";
  /** 用户反馈评分：1=赞(👍)，-1=踩(👎)，null/undefined=未评价。 */
  feedbackRating?: number | null;
  /** 用户反馈的文字意见。 */
  feedbackComment?: string | null;
};

/** 消息反馈评分：1=赞(👍)，-1=踩(👎)，0=取消已有评价。 */
export type MessageFeedbackRating = 1 | -1 | 0;

export type Artifact = {
  fileName: string;
  contentType: "document" | "image";
  content: string;
  fileDataUrl?: string;
};

type ChatWidgetProps = {
  messages: ChatMessageItem[];
  disabled?: boolean;
  disabledReason?: string;
  onSend: (content: string, files?: File[]) => Promise<void>;
  onStopStreaming?: () => void;
  onRegenerateAssistantMessage?: (message: ChatMessageItem) => Promise<void>;
  onResendUserMessage?: (
    message: ChatMessageItem,
    content: string,
  ) => Promise<void>;
  /**
   * 对一条 assistant 回复提交反馈（👍 / 👎 + 可选文字意见）。
   * rating: 1=赞，-1=踩，0=取消已有评价。提供该回调时才渲染反馈按钮。
   */
  onSubmitFeedback?: (
    message: ChatMessageItem,
    rating: MessageFeedbackRating,
    comment?: string,
  ) => Promise<void>;
  loading?: boolean;
  isStreaming?: boolean;
  className?: string;
  /**
   * 在消息列表底部、输入框上方插入的自定义节点，用于内嵌富交互卡片
   * （如外部页面 iframe）。跟随消息流滚动，平级出现在最后一条消息之后。
   */
  messageListFooterSlot?: React.ReactNode;
};

const MESSAGE_TIME_GAP_MS = 5 * 60 * 1000;
const BOTTOM_SCROLL_THRESHOLD = 96;
const MAX_FILES_PER_MESSAGE = 5;

// 空对话欢迎页的「快捷操作」胶囊：点击后把示例问题直接作为一条用户消息发出，
// 降低用户的阅读与打字成本。可按实际业务自定义。
const QUICK_ACTIONS: ReadonlyArray<{
  icon: typeof ClipboardList;
  label: string;
  iconColor: string;
  iconBg: string;
  prompt: string;
}> = [
  {
    icon: ClipboardList,
    label: "使用示例",
    iconColor: "#4A86E8",
    iconBg: "#E6F0FE",
    prompt: "你能帮我做什么？",
  },
  {
    icon: Network,
    label: "功能介绍",
    iconColor: "#7C5CFC",
    iconBg: "#EEEAFE",
    prompt: "介绍一下你的功能。",
  },
];

const QUICK_EXAMPLE = "例如：你能帮我做什么、介绍一下你的功能…";

const ACCEPTED_FILE_EXTENSIONS =
  ".txt,.md,.pdf,.doc,.docx,.xlsx,.html,.htm,.csv,.jpg,.jpeg,.png,.gif,.webp";

const IMAGE_EXTENSIONS = new Set([
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
]);

function isImageFile(file: File): boolean {
  const ext = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  return IMAGE_EXTENSIONS.has(ext);
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const DOC_ATTACHMENT_RE = /\n\n---\n\[文件: ([^\]]+)\]\n[\s\S]*?\n---/g;
const DOC_ARTIFACT_RE = /\n\n---\n\[文件: ([^\]]+)\]\n([\s\S]*?)\n---/g;
const FILE_DATA_URL_RE = /\n\n\[文件数据:([^\]]+)\]\((data:[^)]+)\)/g;

const NODE_REPORT_MARKER_RE =
  /^\s*<!--\s*node-report\s+seq=(\d+)\s+code=(\S+)\s+status=(success|failed)(?:\s+name="([^"]*)")?\s*-->\s*\n?/;
const NODE_REPORT_JSON_BLOCK_RE = /```json\s*\n([\s\S]*?)\n```/;
const NODE_REPORT_TRUNCATE_TAIL = "\n... (已截断)";

type NodeReportPayload = {
  seq: number;
  code: string;
  status: "success" | "failed";
  name: string | null;
  body: string;
};

function parseNodeReportMarker(content: string): NodeReportPayload | null {
  const m = content.match(NODE_REPORT_MARKER_RE);
  if (!m) return null;
  return {
    seq: Number(m[1]),
    code: m[2],
    status: m[3] as "success" | "failed",
    name: m[4] ?? null,
    body: content.slice(m[0].length),
  };
}

function extractNodeReportJson(body: string): {
  data: Record<string, unknown> | null;
  truncated: boolean;
  rawText: string | null;
} {
  const m = body.match(NODE_REPORT_JSON_BLOCK_RE);
  if (!m) return { data: null, truncated: false, rawText: null };
  let raw = m[1];
  let truncated = false;
  if (raw.endsWith(NODE_REPORT_TRUNCATE_TAIL)) {
    truncated = true;
    raw = raw.slice(0, raw.length - NODE_REPORT_TRUNCATE_TAIL.length);
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return {
        data: parsed as Record<string, unknown>,
        truncated,
        rawText: raw,
      };
    }
  } catch {
    // fall through
  }
  return { data: null, truncated, rawText: raw };
}

function extractNodeReportError(body: string): string {
  const m = body.match(/错误信息[：:]\s*([\s\S]*)/);
  return (m ? m[1] : body).trim() || "未知错误";
}

function extractArtifacts(content: string): Artifact[] {
  const artifacts: Artifact[] = [];
  let match: RegExpExecArray | null;

  const fileDataUrls = new Map<string, string>();
  FILE_DATA_URL_RE.lastIndex = 0;
  while ((match = FILE_DATA_URL_RE.exec(content)) !== null) {
    fileDataUrls.set(match[1], match[2]);
  }

  DOC_ARTIFACT_RE.lastIndex = 0;
  while ((match = DOC_ARTIFACT_RE.exec(content)) !== null) {
    artifacts.push({
      fileName: match[1],
      contentType: "document",
      content: match[2],
      fileDataUrl: fileDataUrls.get(match[1]),
    });
  }

  DATA_IMAGE_RE.lastIndex = 0;
  while ((match = DATA_IMAGE_RE.exec(content)) !== null) {
    artifacts.push({
      fileName: match[1] || "image",
      contentType: "image",
      content: match[2],
    });
  }

  return artifacts;
}

function stripAttachmentBlocks(content: string): string {
  return content
    .replace(DOC_ATTACHMENT_RE, "")
    .replace(FILE_DATA_URL_RE, "")
    .trim();
}

function TypingDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex gap-1 text-slate-400", className)}>
      <span className="animate-bounce">·</span>
      <span className="animate-bounce" style={{ animationDelay: "0.1s" }}>
        ·
      </span>
      <span className="animate-bounce" style={{ animationDelay: "0.2s" }}>
        ·
      </span>
    </span>
  );
}

const PLAN_STATE_LABELS: Record<ChatPlanState, string> = {
  todo: "待执行",
  in_progress: "执行中",
  done: "已完成",
  abandoned: "已放弃",
};

const PLAN_STATE_STYLES: Record<ChatPlanState, string> = {
  todo: "border-slate-300 bg-white text-slate-400",
  in_progress: "border-[#4C84FF] bg-[#EFF4FF] text-[#315FC7]",
  done: "border-[#24A148] bg-[#EAF7EF] text-[#1F7A3A]",
  abandoned: "border-[#D95C5C] bg-[#FFF1F1] text-[#A63A3A]",
};

function PlanTaskIcon({ state }: { state: ChatPlanState }) {
  if (state === "done") {
    return <Check className="h-3.5 w-3.5" />;
  }
  if (state === "in_progress") {
    return <LoaderCircle className="h-3.5 w-3.5 animate-spin" />;
  }
  if (state === "abandoned") {
    return <X className="h-3.5 w-3.5" />;
  }
  return <Square className="h-3.5 w-3.5" />;
}

function PlanTodoList({ plan }: { plan: ChatPlanPayload }) {
  if (plan.subtasks.length === 0) {
    return null;
  }

  const doneCount = plan.subtasks.filter((task) => task.state === "done").length;
  const displayState =
    doneCount === plan.subtasks.length ? "done" : plan.state;
  const activeTask =
    displayState === "done"
      ? undefined
      : plan.subtasks.find((task) => task.state === "in_progress");

  return (
    <section className="mb-3 overflow-hidden rounded-lg border border-[#E7ECF3] bg-[#F8FAFF] text-slate-100 shadow-sm">
      <div className="flex min-w-0 items-start justify-between gap-3 border-b border-[#E7ECF3] px-3.5 py-3">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 text-xs font-semibold text-[#4C84FF]">
              计划
            </span>
            <p className="truncate text-sm font-semibold text-slate-100">
              {plan.name || "执行计划"}
            </p>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {doneCount}/{plan.subtasks.length} 完成 ·{" "}
            {PLAN_STATE_LABELS[displayState]}
          </p>
        </div>
        {activeTask ? (
          <span className="max-w-[46%] shrink-0 truncate rounded-full border border-[#D6E3FF] bg-white px-2.5 py-1 text-xs text-[#315FC7]">
            {activeTask.index + 1}. {activeTask.name}
          </span>
        ) : null}
      </div>
      <ol className="divide-y divide-[#E7ECF3]">
        {plan.subtasks.map((task) => (
          <li key={`${task.index}-${task.name}`} className="flex gap-3 px-3.5 py-3">
            <span
              className={cn(
                "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                PLAN_STATE_STYLES[task.state],
              )}
              title={PLAN_STATE_LABELS[task.state]}
            >
              <PlanTaskIcon state={task.state} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <p className="truncate text-sm font-medium text-slate-100">
                  {task.name}
                </p>
                <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500">
                  {PLAN_STATE_LABELS[task.state]}
                </span>
              </div>
              {task.outcome ? (
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                  {task.outcome}
                </p>
              ) : task.description ? (
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                  {task.description}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function NodeReportObject({
  value,
  depth = 0,
}: {
  value: Record<string, unknown>;
  depth?: number;
}) {
  const entries = Object.entries(value);
  if (entries.length === 0) {
    return <span className="text-xs text-slate-400">{"{}"}</span>;
  }

  if (depth === 0) {
    return (
      <dl className="divide-y divide-[#EEF2F7]">
        {entries.map(([k, v]) => (
          <div
            key={k}
            className="grid grid-cols-1 gap-x-4 py-2.5 first:pt-0 last:pb-0 sm:grid-cols-[minmax(72px,108px)_1fr]"
          >
            <dt className="pt-0.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {k}
            </dt>
            <dd className="min-w-0 text-[13px] leading-6 text-slate-100">
              <NodeReportValue value={v} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return (
    <dl className="space-y-1.5 border-l border-[#E7ECF3] pl-3">
      {entries.map(([k, v]) => (
        <div
          key={k}
          className="grid grid-cols-1 gap-x-3 gap-y-0.5 sm:grid-cols-[minmax(64px,max-content)_1fr]"
        >
          <dt className="pt-0.5 text-[12px] font-medium text-slate-300">
            {k}
          </dt>
          <dd className="min-w-0 text-[13px] leading-6 text-slate-100">
            <NodeReportValue value={v} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function NodeReportValue({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-400">—</span>;
  }
  if (typeof value === "boolean") {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded px-1.5 py-px font-mono text-[11.5px]",
          value
            ? "bg-[#E5F0FF] text-[#1E5BD6]"
            : "bg-[#F3F5F9] text-slate-400",
        )}
      >
        {String(value)}
      </span>
    );
  }
  if (typeof value === "number") {
    return (
      <span className="font-mono text-[12.5px] text-slate-100">
        {String(value)}
      </span>
    );
  }
  if (typeof value === "string") {
    return (
      <span className="block whitespace-pre-wrap break-words leading-6 text-slate-100">
        {value}
      </span>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-slate-400">[]</span>;
    }
    const allPrimitive = value.every(
      (item) =>
        item === null ||
        ["string", "number", "boolean"].includes(typeof item),
    );
    if (allPrimitive) {
      return (
        <ul className="my-0.5 list-disc space-y-0.5 pl-5 marker:text-slate-400">
          {value.map((item, i) => (
            <li key={i} className="break-words leading-6 text-slate-100">
              {item === null || item === undefined || item === ""
                ? "—"
                : String(item)}
            </li>
          ))}
        </ul>
      );
    }
    return (
      <ol className="my-0.5 space-y-2 pl-0">
        {value.map((item, i) => (
          <li
            key={i}
            className="border-l border-[#E7ECF3] pl-3"
          >
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
              # {i + 1}
            </div>
            <NodeReportValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    return (
      <NodeReportObject
        value={value as Record<string, unknown>}
        depth={depth}
      />
    );
  }
  return (
    <span className="break-words text-slate-100">{String(value)}</span>
  );
}

function NodeReportCard({
  report,
}: {
  report: NodeReportPayload;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const ok = report.status === "success";
  const { data, truncated, rawText } = useMemo(
    () => extractNodeReportJson(report.body),
    [report.body],
  );

  const errorMessage = ok ? null : extractNodeReportError(report.body);
  const entries = data ? Object.entries(data) : [];

  const accent = ok
    ? {
        border: "border-[#E7ECF3]",
        headerBg: "bg-[#FAFBFD]",
        badge: "bg-[#E5F0FF] text-[#1E5BD6]",
        dot: "bg-[#1E5BD6]",
      }
    : {
        border: "border-[#F4C7C7]",
        headerBg: "bg-[#FFF5F5]",
        badge: "bg-[#FBE3E3] text-[#B42121]",
        dot: "bg-[#B42121]",
      };

  return (
    <div
      className={cn(
        "my-1 overflow-hidden rounded-2xl border bg-white text-sm",
        accent.border,
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((s) => !s)}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition hover:bg-black/[0.02]",
          accent.headerBg,
        )}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
              accent.badge,
            )}
          >
            <span
              className={cn("h-1.5 w-1.5 rounded-full", accent.dot)}
              aria-hidden
            />
            {ok ? "已完成" : "执行失败"}
          </span>
          <span className="flex min-w-0 items-baseline gap-2 truncate text-sm font-medium text-slate-100">
            <span className="shrink-0 text-slate-400">节点 {report.seq}</span>
            <span className="truncate">{report.name || report.code}</span>
            {report.name && report.name !== report.code && (
              <span className="hidden truncate font-mono text-[12px] text-slate-400 sm:inline">
                {report.code}
              </span>
            )}
          </span>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>

      {expanded && (
        <div className="border-t border-[#EEF2F7] px-4 py-3">
          {ok ? (
            <>
              {data && entries.length > 0 ? (
                <NodeReportObject value={data} depth={0} />
              ) : rawText ? (
                <pre className="scrollbar-subtle overflow-x-auto rounded-md bg-[#F8FAFF] p-3 font-mono text-xs text-slate-100">
                  {rawText}
                </pre>
              ) : (
                <p className="text-sm text-slate-500">已完成,无返回数据。</p>
              )}

              {truncated && (
                <p className="mt-2 text-xs text-slate-500">
                  · 结果较长,展示已截断
                </p>
              )}

              {(data || rawText) && (
                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    onClick={() => setShowRaw((s) => !s)}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 transition hover:bg-[#F3F6FB] hover:text-slate-300"
                  >
                    <ChevronDown
                      className={cn(
                        "h-3.5 w-3.5 transition-transform",
                        showRaw && "rotate-180",
                      )}
                    />
                    {showRaw ? "隐藏原始 JSON" : "查看原始 JSON"}
                  </button>
                </div>
              )}

              {showRaw && (data || rawText) && (
                <CodeBlock
                  code={
                    data
                      ? JSON.stringify(data, null, 2)
                      : (rawText ?? "")
                  }
                  className="font-mono text-xs text-slate-100"
                />
              )}
            </>
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm text-rose-400">
              {errorMessage}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ActionTimelineItem({ action }: { action: ChatAgentAction }) {
  const [open, setOpen] = useState(false);
  const argsText = useMemo(() => {
    if (!action.arguments) return "";
    try {
      return JSON.stringify(action.arguments, null, 2);
    } catch {
      return String(action.arguments);
    }
  }, [action.arguments]);

  const Icon =
    action.status === "running"
      ? LoaderCircle
      : action.status === "error"
        ? AlertCircle
        : Wrench;

  const tone =
    action.status === "running"
      ? "text-[#7C8DAF]"
      : action.status === "error"
        ? "text-[#E5484D]"
        : "text-[#3F8E5B]";

  return (
    <div className="rounded-lg border border-[#E7ECF3] bg-white">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 flex-shrink-0 text-slate-400 transition-transform",
            open && "rotate-90",
          )}
        />
        <Icon
          className={cn(
            "h-3.5 w-3.5 flex-shrink-0",
            tone,
            action.status === "running" && "animate-spin",
          )}
        />
        <span className="font-medium text-slate-700">
          {action.name || "tool"}
        </span>
        <span className="ml-auto text-[10px] text-slate-400">
          {action.status === "running"
            ? "执行中"
            : action.status === "error"
              ? "失败"
              : "成功"}
        </span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-[#E7ECF3] px-2.5 py-2 text-xs">
          {argsText ? (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
                参数
              </div>
              <pre className="scrollbar-subtle max-h-40 overflow-auto rounded-md bg-[#F8FAFF] p-2 text-[11px] text-slate-700">
                {argsText}
              </pre>
            </div>
          ) : null}
          {action.output ? (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
                结果
              </div>
              <pre className="scrollbar-subtle max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-[#F8FAFF] p-2 text-[11px] text-slate-700">
                {action.output}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ActionTimeline({ actions }: { actions: ChatAgentAction[] }) {
  const [open, setOpen] = useState(true);
  if (actions.length === 0) return null;
  const running = actions.some((a) => a.status === "running");
  const errored = actions.some((a) => a.status === "error");
  const summary = running
    ? "工具执行中"
    : errored
      ? "包含失败的工具调用"
      : `已完成 ${actions.length} 个工具调用`;
  return (
    <div className="mb-2 rounded-xl border border-[#E7ECF3] bg-[#F8FAFF] p-2">
      <button
        type="button"
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-slate-600"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            !open && "-rotate-90",
          )}
        />
        <Wrench className="h-3.5 w-3.5 text-slate-500" />
        {summary}
      </button>
      {open ? (
        <div className="mt-2 space-y-1.5">
          {actions.map((a, idx) => (
            <ActionTimelineItem key={a.id ?? idx} action={a} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ThinkingPanel({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;
  return (
    <div className="mb-2 rounded-xl border border-dashed border-[#E7ECF3] bg-white p-2">
      <button
        type="button"
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-slate-500"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            !open && "-rotate-90",
          )}
        />
        <Brain className="h-3.5 w-3.5 text-slate-400" />
        模型思考
      </button>
      {open ? (
        <pre className="scrollbar-subtle mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-[#F8FAFF] p-2 text-[11px] text-slate-600">
          {text}
        </pre>
      ) : null}
    </div>
  );
}

/**
 * 子专家正在输出最终回复时（``node.text_delta`` 事件）的实时预览面板。
 * 与 :func:`ThinkingPanel` 不同——这里展示的是子专家**对外**的回答文本
 * （区别于内部 reasoning 独白），所以默认展开 + 用蓝色强调，让用户清楚
 * "这一坨就是子专家最终想说的话"。
 */
export function LiveAssistantTextPanel({ text }: { text: string }) {
  const [open, setOpen] = useState(true);
  if (!text.trim()) return null;
  return (
    <div className="mb-2 rounded-xl border border-[#D6E4FF] bg-[#F5F9FF] p-2">
      <button
        type="button"
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-[#4C84FF]"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            !open && "-rotate-90",
          )}
        />
        子专家正在输出…
      </button>
      {open ? (
        <pre className="scrollbar-subtle mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-white p-2 text-[11px] leading-relaxed text-slate-700">
          {text}
        </pre>
      ) : null}
    </div>
  );
}

/**
 * 静态兜底的工具名清单：用于在 AI 回复正文里把内部工具标识符替换成通用字眼，
 * 避免把实现细节暴露给终端用户。运行时还会叠加该条消息实际调用过的工具名
 * （见 ``sanitizeToolNames``），因此新增工具一般无需在此手动登记。
 */
const TOOL_NAME_FALLBACK = [
  "get_current_time",
  "load_skill",
  "run_plan",
  "update_plan_step",
];

/** 替换后展示给用户的通用字眼。 */
const TOOL_NAME_MASK = "相关工具";

/**
 * 把文本中出现的工具名（含可能包裹的反引号）替换为通用字眼。
 * 仅匹配完整 token，避免误伤普通文字。
 */
function sanitizeToolNames(text: string, extraNames: string[] = []): string {
  if (!text) return text;
  const names = Array.from(
    new Set([...TOOL_NAME_FALLBACK, ...extraNames]),
  ).filter(Boolean);
  if (names.length === 0) return text;
  const pattern = names
    .map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length)
    .join("|");
  const re = new RegExp("`?\\b(?:" + pattern + ")\\b`?", "g");
  return text.replace(re, TOOL_NAME_MASK);
}

function AssistantMessageContent({
  content,
  generationState,
  onOpenArtifact,
  plan,
  actions,
  thinking,
}: {
  content: string;
  generationState?: "streaming" | "stopped";
  onOpenArtifact?: (artifact: Artifact) => void;
  plan?: ChatPlanPayload;
  actions?: ChatAgentAction[];
  thinking?: string;
}) {
  // plan 模式下助手叙述默认展开，方便用户直接看到每步「执行说明」全文；
  // 仍保留折叠按钮，需要时可手动收起。
  const [detailsOpen, setDetailsOpen] = useState(true);
  const hasContent = Boolean(content.trim());
  const hasActions = Array.isArray(actions) && actions.length > 0;
  const hasThinking = Boolean(thinking && thinking.trim());

  if (
    generationState === "streaming" &&
    !hasContent &&
    !plan &&
    !hasActions &&
    !hasThinking
  ) {
    return <TypingDots />;
  }

  if (
    generationState === "stopped" &&
    !hasContent &&
    !plan &&
    !hasActions &&
    !hasThinking
  ) {
    return <p className="text-sm text-slate-400">已暂停生成</p>;
  }

  const nodeReport = parseNodeReportMarker(content);
  if (nodeReport && !plan && !hasActions && !hasThinking) {
    return <NodeReportCard report={nodeReport} />;
  }

  const actionToolNames = (actions ?? [])
    .map((a) => a.name)
    .filter((n): n is string => Boolean(n));
  const displayContent = sanitizeToolNames(content, actionToolNames);

  const markdown = (
    <MarkdownContent
      content={displayContent}
      onOpenArtifact={
        generationState === "streaming" ? undefined : onOpenArtifact
      }
    />
  );

  return (
    <>
      {hasThinking ? <ThinkingPanel text={thinking!} /> : null}
      {hasActions ? <ActionTimeline actions={actions!} /> : null}
      {plan ? <PlanTodoList plan={plan} /> : null}
      {hasContent && plan ? (
        <div className="mt-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-[#F3F6FB] hover:text-slate-200"
            onClick={() => setDetailsOpen((open) => !open)}
          >
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 transition-transform",
                detailsOpen && "rotate-180",
              )}
            />
            执行说明
          </button>
          {detailsOpen ? (
            <div className="mt-2 rounded-lg border border-[#E7ECF3] bg-white px-3 py-2">
              {markdown}
            </div>
          ) : null}
        </div>
      ) : hasContent ? (
        markdown
      ) : null}
    </>
  );
}

function CodeBlock({ code, className }: { code: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore copy errors in unsupported contexts
    }
  };

  return (
    <div className="relative my-2 min-w-0">
      <button
        type="button"
        className="absolute right-2 top-2 rounded-lg bg-[#EFF4FF] px-2 py-1 text-xs text-slate-200 transition hover:bg-[#DCE7FF]"
        onClick={handleCopy}
      >
        {copied ? "已复制" : "复制"}
      </button>
      <pre className="scrollbar-subtle overflow-x-auto rounded-xl border border-[#E7ECF3] bg-[#F8FAFF] p-3 text-left">
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

function extractTextContent(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") {
        return String(child);
      }
      if (isValidElement<{ children?: ReactNode }>(child)) {
        return extractTextContent(child.props.children);
      }
      return "";
    })
    .join("");
}

function isNearBottom(element: HTMLDivElement): boolean {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    BOTTOM_SCROLL_THRESHOLD
  );
}

function formatMessageTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const now = new Date();
  const formatter = new Intl.DateTimeFormat("zh-CN", {
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  return formatter.format(date);
}

function shouldShowTimestamp(
  current: ChatMessageItem,
  previous?: ChatMessageItem,
): boolean {
  if (!previous) {
    return true;
  }

  const currentDate = new Date(current.created_at);
  const previousDate = new Date(previous.created_at);
  if (
    Number.isNaN(currentDate.getTime()) ||
    Number.isNaN(previousDate.getTime())
  ) {
    return false;
  }

  return (
    currentDate.toDateString() !== previousDate.toDateString() ||
    currentDate.getTime() - previousDate.getTime() >= MESSAGE_TIME_GAP_MS
  );
}

// data: URL 图片（如截图）不能通过 react-markdown 渲染（v8+ 在 AST 层过滤），
// 需要在传入前提取出来，直接用 <img> 渲染。
const DATA_IMAGE_RE = /!\[([^\]]*)\]\((data:image\/[^)]+)\)/g;
const BARE_URL_RE = /https?:\/\/[^\s<>()\[\]{}"'`]+/g;
const URL_TEXT_BOUNDARY_RE =
  /[\u3000-\u303F\u3400-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/u;
const URL_TRAILING_ASCII_PUNCTUATION_RE = /[.,!?;:]+$/;

type ContentPart =
  | { type: "text"; text: string }
  | { type: "data-image"; alt: string; src: string };

function splitDataImages(raw: string): ContentPart[] {
  const parts: ContentPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  DATA_IMAGE_RE.lastIndex = 0;
  while ((match = DATA_IMAGE_RE.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", text: raw.slice(lastIndex, match.index) });
    }
    parts.push({ type: "data-image", alt: match[1], src: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < raw.length) {
    parts.push({ type: "text", text: raw.slice(lastIndex) });
  }
  return parts;
}

function normalizeBareUrlsForMarkdown(text: string): string {
  return text.replace(
    BARE_URL_RE,
    (rawUrl: string, offset: number, fullText: string) => {
      const previousChar = fullText[offset - 1];
      const previousPreviousChar = fullText[offset - 2];
      if (
        previousChar === "<" ||
        (previousChar === "(" && previousPreviousChar === "]")
      ) {
        return rawUrl;
      }

      const textBoundaryIndex = rawUrl.search(URL_TEXT_BOUNDARY_RE);
      if (textBoundaryIndex >= 0) {
        const url = rawUrl.slice(0, textBoundaryIndex);
        const trailingText = rawUrl.slice(textBoundaryIndex);
        return url ? `<${url}>${trailingText}` : rawUrl;
      }

      const url = rawUrl.replace(URL_TRAILING_ASCII_PUNCTUATION_RE, "");
      if (url !== rawUrl) {
        return `<${url}>${rawUrl.slice(url.length)}`;
      }

      return rawUrl;
    },
  );
}

function parseTableFromDOM(table: HTMLTableElement): string[][] {
  const rows: string[][] = [];
  table.querySelectorAll("tr").forEach((tr) => {
    const cells: string[] = [];
    tr.querySelectorAll("th, td").forEach((cell) => {
      cells.push(cell.textContent?.trim() ?? "");
    });
    if (cells.length > 0) rows.push(cells);
  });
  return rows;
}

async function tableDataToXlsxBlob(rows: string[][]): Promise<Blob> {
  const XLSX = await import("xlsx");
  const ws = XLSX.utils.aoa_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
  const buf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
  return new Blob([buf], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// 文件下载链接识别：导出目录（工具产出的文件）或常见文档后缀。
const FILE_DOWNLOAD_URL_RE =
  /\.(xlsx|xls|csv|docx|doc|pdf|pptx|ppt|zip|rar|7z|txt)([?#]|$)/i;

function isFileDownloadUrl(href: string): boolean {
  return href.includes("/static/exports/") || FILE_DOWNLOAD_URL_RE.test(href);
}

/**
 * 嵌入 iframe 场景下，文件下载不由 iframe 内直接触发（宿主常为 App WebView，
 * 直接点链接会失败），改为 postMessage 把下载地址交给宿主页面去下载。
 * 返回 true 表示已交给宿主处理（调用方应 preventDefault）。
 */
function relayDownloadToParent(href: string): boolean {
  if (typeof window === "undefined") return false;
  if (window.self === window.parent) return false;
  if (!isFileDownloadUrl(href)) return false;
  try {
    const parsed = new URL(href, window.location.href);
    const relativeUrl = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    window.parent.postMessage({ type: "fileDownLoad", url: relativeUrl }, "*");
    return true;
  } catch {
    return false;
  }
}

function TableWithToolbar({
  children,
  className,
  onOpenArtifact,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement> & {
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const tableRef = useRef<HTMLTableElement>(null);

  const exportToArtifact = useCallback(async () => {
    if (!tableRef.current || !onOpenArtifact) return;
    const rows = parseTableFromDOM(tableRef.current);
    if (rows.length === 0) return;
    const blob = await tableDataToXlsxBlob(rows);
    const buf = await blob.arrayBuffer();
    const b64 = btoa(
      new Uint8Array(buf).reduce((s, b) => s + String.fromCharCode(b), ""),
    );
    const dataUrl = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${b64}`;
    onOpenArtifact({
      fileName: "table.xlsx",
      contentType: "document",
      content: rows.map((r) => r.join("\t")).join("\n"),
      fileDataUrl: dataUrl,
    });
  }, [onOpenArtifact]);

  const exportDownload = useCallback(async () => {
    if (!tableRef.current) return;
    const rows = parseTableFromDOM(tableRef.current);
    if (rows.length === 0) return;
    const blob = await tableDataToXlsxBlob(rows);
    downloadBlob(blob, "table.xlsx");
  }, []);

  return (
    <div className="group/table relative my-3">
      {onOpenArtifact && (
        <div className="pointer-events-none absolute -top-1 right-0 z-10 flex items-center gap-1 rounded-lg border border-[#E7ECF3] bg-white px-1 py-0.5 opacity-0 shadow-sm transition-opacity duration-150 group-hover/table:pointer-events-auto group-hover/table:opacity-100">
          <button
            type="button"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-300 transition hover:bg-[#F3F6FB] hover:text-slate-100"
            onClick={() => void exportToArtifact()}
          >
            <Table2 className="h-3 w-3" />
            在面板中查看
          </button>
          <button
            type="button"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-300 transition hover:bg-[#F3F6FB] hover:text-slate-100"
            onClick={() => void exportDownload()}
          >
            <Download className="h-3 w-3" />
            导出 Excel
          </button>
        </div>
      )}
      <div className="scrollbar-subtle overflow-x-auto">
        <table
          ref={tableRef}
          {...props}
          className={cn("min-w-full border-collapse text-left text-xs", className)}
        >
          {children}
        </table>
      </div>
    </div>
  );
}

function MarkdownContent({
  content,
  onOpenArtifact,
}: {
  content: string;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const markdownComponents: Components = {
    a: ({ className, children, href, ...props }) => (
      <a
        {...props}
        href={href}
        className={cn(
          "text-[#4C84FF] underline decoration-[#4C84FF]/30 underline-offset-2 transition-colors hover:text-[#3F76EE]",
          className,
        )}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(event) => {
          if (href && relayDownloadToParent(href)) {
            event.preventDefault();
          }
        }}
        onTouchEnd={(event) => {
          if (href && relayDownloadToParent(href)) {
            event.preventDefault();
          }
        }}
      >
        {children}
      </a>
    ),
    p: ({ className, children, ...props }) => (
      <p
        {...props}
        className={cn("my-2 whitespace-pre-wrap break-words leading-7", className)}
      >
        {children}
      </p>
    ),
    h1: ({ className, children, ...props }) => (
      <h1
        {...props}
        className={cn("mb-3 mt-4 text-lg font-semibold text-slate-50", className)}
      >
        {children}
      </h1>
    ),
    h2: ({ className, children, ...props }) => (
      <h2
        {...props}
        className={cn("mb-3 mt-4 text-base font-semibold text-slate-50", className)}
      >
        {children}
      </h2>
    ),
    h3: ({ className, children, ...props }) => (
      <h3
        {...props}
        className={cn("mb-2 mt-4 text-sm font-semibold text-slate-50", className)}
      >
        {children}
      </h3>
    ),
    ul: ({ className, children, ...props }) => (
      <ul
        {...props}
        className={cn(
          "my-2 list-disc space-y-1.5 pl-5 marker:text-[#9AB4F0]",
          className,
        )}
      >
        {children}
      </ul>
    ),
    ol: ({ className, children, ...props }) => (
      <ol
        {...props}
        className={cn(
          "my-2 list-decimal space-y-1.5 pl-5 marker:font-semibold marker:text-[#4C84FF]",
          className,
        )}
      >
        {children}
      </ol>
    ),
    li: ({ className, children, ...props }) => (
      <li {...props} className={cn("pl-1 leading-[1.7]", className)}>
        {children}
      </li>
    ),
    blockquote: ({ className, children, ...props }) => (
      <blockquote
        {...props}
        className={cn(
          "my-3 border-l-2 border-[#4C84FF]/28 pl-4 text-slate-300",
          className,
        )}
      >
        {children}
      </blockquote>
    ),
    hr: ({ className, ...props }) => (
      <hr {...props} className={cn("my-4 border-[#E7ECF3]", className)} />
    ),
    table: ({ className, children, ...props }) => (
      <TableWithToolbar
        {...props}
        className={className}
        onOpenArtifact={onOpenArtifact}
      >
        {children}
      </TableWithToolbar>
    ),
    th: ({ className, children, ...props }) => (
      <th
        {...props}
        className={cn(
          "border border-[#E7ECF3] bg-[#F8FAFF] px-3 py-2 font-medium text-slate-100",
          className,
        )}
      >
        {children}
      </th>
    ),
    td: ({ className, children, ...props }) => (
      <td
        {...props}
        className={cn("border border-[#E7ECF3] px-3 py-2 text-slate-200", className)}
      >
        {children}
      </td>
    ),
    img: ({ className, alt = "", src, ...props }) =>
      src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          {...props}
          src={src}
          alt={alt}
          className={cn("my-3 max-w-full rounded-md border border-[#E7ECF3]", className)}
        />
      ) : null,
    pre: ({ children }) => {
      const codeElement = Children.toArray(children).find((child) =>
        isValidElement<{ className?: string }>(child),
      );
      const className =
        codeElement && isValidElement<{ className?: string }>(codeElement)
          ? codeElement.props.className
          : undefined;

      return (
        <CodeBlock
          code={extractTextContent(children).replace(/\n$/, "")}
          className={cn("font-mono text-xs text-slate-100", className)}
        />
      );
    },
    code: ({ className, children, ...props }) => {
      const raw = String(children ?? "");
      const isBlock = className?.includes("language-") || raw.includes("\n");

      if (isBlock) {
        return (
          <code
            {...props}
            className={cn("font-mono text-xs text-slate-100", className)}
          >
            {raw.replace(/\n$/, "")}
          </code>
        );
      }

      // 模型常把下载地址包在反引号里输出,渲染成 <code> 后不可点击,
      // 嵌入方也收不到 fileDownLoad 消息。这里兜底识别成可点击链接。
      const inlineUrl = raw.trim();
      const looksLikeUrl =
        !/\s/.test(inlineUrl) && /^(https?:\/\/|\/)/i.test(inlineUrl);
      if (looksLikeUrl && isFileDownloadUrl(inlineUrl)) {
        return (
          <a
            href={inlineUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "rounded bg-[#EFF4FF] px-1 py-0.5 font-mono text-[0.9em] text-[#4C84FF] underline decoration-[#4C84FF]/30 underline-offset-2 transition-colors hover:text-[#3F76EE]",
              className,
            )}
            onClick={(event) => {
              if (relayDownloadToParent(inlineUrl)) {
                event.preventDefault();
              }
            }}
            onTouchEnd={(event) => {
              if (relayDownloadToParent(inlineUrl)) {
                event.preventDefault();
              }
            }}
          >
            {children}
          </a>
        );
      }

      return (
        <code
          {...props}
          className={cn(
            "rounded bg-[#EFF4FF] px-1 py-0.5 font-mono text-[0.9em] text-slate-100",
            className,
          )}
        >
          {children}
        </code>
      );
    },
  };

  const parts = splitDataImages(content);

  return (
    <div className="min-w-0 max-w-none text-sm text-slate-100">
      {parts.map((part, i) =>
        part.type === "data-image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={i}
            src={part.src}
            alt={part.alt}
            className="my-3 max-w-full rounded-md border border-[#E7ECF3]"
          />
        ) : (
          <ReactMarkdown
            key={i}
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={markdownComponents}
          >
            {normalizeBareUrlsForMarkdown(part.text)}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}

function UserMessageBubble({
  content,
  onOpenArtifact,
}: {
  content: string;
  onOpenArtifact?: (artifact: Artifact) => void;
}) {
  const artifacts = extractArtifacts(content);
  const docArtifacts = artifacts.filter((a) => a.contentType === "document");
  const imgArtifacts = artifacts.filter((a) => a.contentType === "image");

  const displayText =
    docArtifacts.length > 0 ? stripAttachmentBlocks(content) : content;
  const parts = splitDataImages(displayText);
  const textParts = parts.filter((p) => p.type === "text");
  const textContent = textParts
    .map((p) => (p.type === "text" ? p.text : ""))
    .join("")
    .trim();

  return (
    <div className="space-y-2">
      {docArtifacts.length > 0 && (
        <div className="flex flex-wrap justify-end gap-1.5">
          {docArtifacts.map((art, i) => (
            <button
              key={`${art.fileName}-${i}`}
              type="button"
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-[#E7ECF3] bg-[#F8FAFF] px-3 py-1 text-xs text-slate-200 transition hover:border-[#4C84FF]/40 hover:bg-[#EFF4FF]"
              onClick={() => onOpenArtifact?.(art)}
            >
              <FileText className="h-3.5 w-3.5 text-[#4C84FF]" />
              {art.fileName}
            </button>
          ))}
        </div>
      )}
      {imgArtifacts.length > 0 && (
        <div className="flex flex-wrap justify-end gap-2">
          {imgArtifacts.map((art, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={i}
              src={art.content}
              alt={art.fileName}
              className="max-h-48 max-w-[240px] cursor-pointer rounded-2xl border border-[#E7ECF3] object-cover transition hover:border-[#4C84FF]/40 hover:shadow-md"
              onClick={() => onOpenArtifact?.(art)}
            />
          ))}
        </div>
      )}
      {textContent && (
        <div className="rounded-[26px] border border-[#E7ECF3] bg-[#F3F5F9] px-5 py-3.5 text-[15px] leading-7 text-slate-100">
          <p className="whitespace-pre-wrap">{textContent}</p>
        </div>
      )}
    </div>
  );
}

function getFileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot >= 0 ? fileName.slice(dot).toLowerCase() : "";
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, b64] = dataUrl.split(",");
  const mime = header.match(/data:([^;]+)/)?.[1] ?? "application/octet-stream";
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

function PdfPreview({ dataUrl }: { dataUrl: string }) {
  const blobUrl = useMemo(() => {
    const blob = dataUrlToBlob(dataUrl);
    return URL.createObjectURL(blob);
  }, [dataUrl]);

  useEffect(() => {
    return () => URL.revokeObjectURL(blobUrl);
  }, [blobUrl]);

  return (
    <iframe
      src={blobUrl}
      title="PDF 预览"
      className="h-full w-full border-0"
    />
  );
}

function DocxPreview({ dataUrl }: { dataUrl: string }) {
  const [html, setHtml] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mammoth = await import("mammoth");
        const blob = dataUrlToBlob(dataUrl);
        const arrayBuffer = await blob.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer });
        if (!cancelled) setHtml(result.value);
      } catch {
        if (!cancelled) setError("无法解析 Word 文档");
      }
    })();
    return () => { cancelled = true; };
  }, [dataUrl]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!html) return <p className="text-sm text-slate-400">正在解析文档…</p>;

  return (
    <div
      className="prose prose-sm max-w-none text-slate-200 prose-headings:text-slate-50 prose-strong:text-slate-100 prose-table:border-collapse prose-th:border prose-th:border-[#E7ECF3] prose-th:bg-[#F8FAFF] prose-th:px-3 prose-th:py-1.5 prose-td:border prose-td:border-[#E7ECF3] prose-td:px-3 prose-td:py-1.5"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function XlsxPreview({ dataUrl }: { dataUrl: string }) {
  const [sheets, setSheets] = useState<
    { name: string; rows: string[][] }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const XLSX = await import("xlsx");
        const blob = dataUrlToBlob(dataUrl);
        const arrayBuffer = await blob.arrayBuffer();
        const workbook = XLSX.read(arrayBuffer, { type: "array" });
        const parsed = workbook.SheetNames.map((name) => {
          const sheet = workbook.Sheets[name];
          const rows = XLSX.utils.sheet_to_json<string[]>(sheet, {
            header: 1,
            defval: "",
          });
          return { name, rows: rows as string[][] };
        });
        if (!cancelled) {
          setSheets(parsed);
          setActiveSheet(0);
        }
      } catch {
        if (!cancelled) setError("无法解析 Excel 文件");
      }
    })();
    return () => { cancelled = true; };
  }, [dataUrl]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (sheets.length === 0)
    return <p className="text-sm text-slate-400">正在解析表格…</p>;

  const current = sheets[activeSheet];

  return (
    <div className="space-y-3">
      {sheets.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              type="button"
              className={cn(
                "rounded-md px-2.5 py-1 text-xs transition",
                i === activeSheet
                  ? "bg-[#4C84FF] text-white"
                  : "bg-[#F3F6FB] text-slate-300 hover:bg-[#E7ECF3]",
              )}
              onClick={() => setActiveSheet(i)}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <tbody>
            {current?.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={cn(
                      "border border-[#E7ECF3] px-2.5 py-1.5 text-slate-200",
                      ri === 0 && "bg-[#F8FAFF] font-medium text-slate-100",
                    )}
                  >
                    {String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const PANEL_MIN_W = 280;
const PANEL_MAX_W = 800;
const PANEL_DEFAULT_W = 420;

function ArtifactPanel({
  artifact,
  visible,
  onClose,
}: {
  artifact: Artifact | null;
  visible: boolean;
  onClose: () => void;
}) {
  const isImage = artifact?.contentType === "image";
  const ext = artifact ? getFileExtension(artifact.fileName) : "";
  const hasNativePreview = Boolean(
    artifact?.fileDataUrl && [".pdf", ".docx", ".doc", ".xlsx"].includes(ext),
  );
  const isMarkdown = [".md", ".markdown"].includes(ext);

  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_W);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  useEffect(() => {
    if (!visible) return;

    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = startXRef.current - e.clientX;
      const newW = Math.min(PANEL_MAX_W, Math.max(PANEL_MIN_W, startWidthRef.current + delta));
      setPanelWidth(newW);
    };

    const onMouseUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [visible]);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    startXRef.current = e.clientX;
    startWidthRef.current = panelWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [panelWidth]);

  const handleDownload = useCallback(() => {
    if (!artifact?.fileDataUrl) return;
    const blob = dataUrlToBlob(artifact.fileDataUrl);
    downloadBlob(blob, artifact.fileName);
  }, [artifact]);

  function renderContent() {
    if (!artifact) return null;

    if (isImage) {
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={artifact.content}
          alt={artifact.fileName}
          className="mx-auto max-w-full rounded-lg border border-[#E7ECF3] object-contain"
        />
      );
    }

    if (artifact.fileDataUrl) {
      if (ext === ".pdf") {
        return <PdfPreview dataUrl={artifact.fileDataUrl} />;
      }
      if (ext === ".docx" || ext === ".doc") {
        return <DocxPreview dataUrl={artifact.fileDataUrl} />;
      }
      if (ext === ".xlsx") {
        return <XlsxPreview dataUrl={artifact.fileDataUrl} />;
      }
    }

    if (isMarkdown) {
      return <MarkdownContent content={artifact.content} />;
    }

    return (
      <pre className="whitespace-pre-wrap break-words text-[13px] leading-6 text-slate-200">
        {artifact.content}
      </pre>
    );
  }

  const isPdf = ext === ".pdf" && artifact?.fileDataUrl;

  return (
    <div
      className={cn(
        "shrink-0 overflow-hidden",
        !draggingRef.current && "transition-[width,opacity] duration-300 ease-in-out",
        visible ? "opacity-100" : "w-0 opacity-0",
      )}
      style={visible ? { width: panelWidth } : undefined}
    >
      <div className="relative flex h-full flex-col border-l border-[#E7ECF3] bg-white" style={{ width: panelWidth, minWidth: PANEL_MIN_W }}>
        {/* resize handle */}
        <div
          className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize hover:bg-[#4C84FF]/20 active:bg-[#4C84FF]/30"
          onMouseDown={handleResizeStart}
        />

        <div className="flex shrink-0 items-center gap-2.5 border-b border-[#EEF2F7] px-4 py-3">
          {isImage ? (
            <ImageIcon className="h-4 w-4 shrink-0 text-[#4C84FF]" />
          ) : (
            <FileText className="h-4 w-4 shrink-0 text-[#4C84FF]" />
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100">
            {artifact?.fileName}
          </span>
          {hasNativePreview && (
            <span className="shrink-0 rounded bg-[#EFF4FF] px-1.5 py-0.5 text-[10px] text-[#4C84FF]">
              原始格式
            </span>
          )}
          {artifact?.fileDataUrl && (
            <button
              type="button"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
              onClick={handleDownload}
              aria-label="下载文件"
              title="下载"
            >
              <Download className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
            onClick={onClose}
            aria-label="关闭预览"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {isPdf ? (
          <div className="min-h-0 flex-1">{renderContent()}</div>
        ) : (
          <ScrollArea className="min-h-0 flex-1">
            <div className="p-5">{renderContent()}</div>
          </ScrollArea>
        )}
      </div>
    </div>
  );
}

/**
 * assistant 回复的反馈控件：👍 / 👎 两个图标 + 可选的文字意见输入。
 *
 * - 点击 👍：直接提交 rating=1（再次点击取消 → rating=0）。
 * - 点击 👎：展开文字意见输入框，提交时带 rating=-1 + comment；
 *   再次点击已选中的 👎 则取消评价（rating=0）。
 * - 当前评分由父级 message.feedbackRating 驱动（提交成功后回写）。
 */
function MessageFeedback({
  message,
  disabled,
  onSubmitFeedback,
}: {
  message: ChatMessageItem;
  disabled?: boolean;
  onSubmitFeedback: (
    message: ChatMessageItem,
    rating: MessageFeedbackRating,
    comment?: string,
  ) => Promise<void>;
}) {
  const rating = message.feedbackRating ?? 0;
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState(message.feedbackComment ?? "");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setComment(message.feedbackComment ?? "");
  }, [message.feedbackComment]);

  const submit = useCallback(
    async (nextRating: MessageFeedbackRating, nextComment?: string) => {
      if (submitting) return;
      setSubmitting(true);
      try {
        await onSubmitFeedback(message, nextRating, nextComment);
      } finally {
        setSubmitting(false);
      }
    },
    [message, onSubmitFeedback, submitting],
  );

  const handleThumbsUp = useCallback(() => {
    setCommentOpen(false);
    void submit(rating === 1 ? 0 : 1);
  }, [rating, submit]);

  const handleThumbsDown = useCallback(() => {
    if (rating === -1) {
      // 已经是「踩」状态：再次点击取消评价并收起输入框。
      setCommentOpen(false);
      void submit(0);
      return;
    }
    setCommentOpen((open) => !open);
  }, [rating, submit]);

  const submitComment = useCallback(() => {
    void submit(-1, comment.trim() || undefined).then(() =>
      setCommentOpen(false),
    );
  }, [comment, submit]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <button
          type="button"
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-[#F3F6FB]",
            rating === 1
              ? "text-[#4A86E8]"
              : "text-slate-400 hover:text-slate-200",
          )}
          onClick={handleThumbsUp}
          disabled={disabled || submitting}
          aria-label="赞同此回复"
          aria-pressed={rating === 1}
          title="赞"
        >
          <ThumbsUp
            className={cn("h-4 w-4", rating === 1 && "fill-current")}
          />
        </button>
        <button
          type="button"
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-[#F3F6FB]",
            rating === -1
              ? "text-[#E5484D]"
              : "text-slate-400 hover:text-slate-200",
          )}
          onClick={handleThumbsDown}
          disabled={disabled || submitting}
          aria-label="不认可此回复"
          aria-pressed={rating === -1}
          title="踩"
        >
          <ThumbsDown
            className={cn("h-4 w-4", rating === -1 && "fill-current")}
          />
        </button>
        {rating === -1 && !commentOpen ? (
          <button
            type="button"
            className="rounded-md px-2 py-1 text-[11px] text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-300"
            onClick={() => setCommentOpen(true)}
            disabled={disabled || submitting}
          >
            {message.feedbackComment ? "修改意见" : "补充意见"}
          </button>
        ) : null}
      </div>

      {commentOpen ? (
        <div className="w-full max-w-[480px] rounded-2xl border border-[#E7ECF3] bg-white p-3 shadow-[0_8px_24px_rgba(31,42,68,0.06)]">
          <Textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="说说哪里不满意，或希望怎样改进？（选填）"
            className="min-h-[64px] resize-none border-0 bg-transparent px-0 py-0 text-sm text-slate-100 shadow-none outline-none ring-0 focus:border-0 focus:ring-0 focus-visible:border-0 focus-visible:ring-0"
          />
          <div className="mt-2 flex items-center justify-end gap-2 border-t border-[#E7ECF3] pt-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setCommentOpen(false);
                setComment(message.feedbackComment ?? "");
              }}
              disabled={submitting}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={submitComment}
              disabled={submitting}
            >
              {submitting ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              提交
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ChatWidget({
  messages,
  disabled = false,
  disabledReason,
  onSend,
  onStopStreaming,
  onRegenerateAssistantMessage,
  onResendUserMessage,
  onSubmitFeedback,
  loading = false,
  isStreaming = false,
  className,
  messageListFooterSlot,
}: ChatWidgetProps) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [messageActionId, setMessageActionId] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [draggingOver, setDraggingOver] = useState(false);
  const [imagePreviews, setImagePreviews] = useState<Record<string, string>>({});
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [artifactVisible, setArtifactVisible] = useState(false);
  const artifactTimerRef = useRef<ReturnType<typeof setTimeout>>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hasMessages = messages.length > 0;
  const showCenteredEmptyState = !hasMessages && !loading;

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior,
      });
    }
  }, []);

  useEffect(() => {
    if (pinnedToBottom) {
      scrollToBottom();
    }
  }, [messages, pinnedToBottom, scrollToBottom]);

  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;

    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
    el.style.overflowY = el.scrollHeight > 220 ? "auto" : "hidden";
  }, [input]);

  useEffect(() => {
    const urls: Record<string, string> = {};
    pendingFiles.forEach((file) => {
      if (isImageFile(file)) {
        urls[file.name + file.size] = URL.createObjectURL(file);
      }
    });
    setImagePreviews(urls);
    return () => {
      Object.values(urls).forEach(URL.revokeObjectURL);
    };
  }, [pendingFiles]);

  const openArtifact = useCallback((artifact: Artifact) => {
    if (artifactTimerRef.current) clearTimeout(artifactTimerRef.current);
    setActiveArtifact(artifact);
    requestAnimationFrame(() => setArtifactVisible(true));
  }, []);

  const closeArtifact = useCallback(() => {
    setArtifactVisible(false);
    artifactTimerRef.current = setTimeout(() => setActiveArtifact(null), 300);
  }, []);

  const addFiles = useCallback(
    (incoming: File[]) => {
      setPendingFiles((prev) => {
        const remaining = MAX_FILES_PER_MESSAGE - prev.length;
        if (remaining <= 0) return prev;
        return [...prev, ...incoming.slice(0, remaining)];
      });
    },
    [],
  );

  const removeFile = useCallback((index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        addFiles(Array.from(e.target.files));
      }
      e.target.value = "";
    },
    [addFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDraggingOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDraggingOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggingOver(false);
      if (disabled || sending) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) addFiles(files);
    },
    [addFiles, disabled, sending],
  );

  const handleSend = async (overrideText?: string) => {
    const useOverride = typeof overrideText === "string";
    const text = useOverride
      ? overrideText.replace(/\r\n/g, "\n").replace(/\s+$/, "")
      : input.replace(/\r\n/g, "\n").replace(/\s+$/, "");
    // 快捷操作（overrideText）只发文本，不带当前待上传文件。
    const hasFiles = !useOverride && pendingFiles.length > 0;
    if ((!text && !hasFiles) || sending || disabled) return;
    const filesToSend = hasFiles ? [...pendingFiles] : undefined;
    if (!useOverride) {
      setInput("");
      setPendingFiles([]);
    }
    setSending(true);
    setPinnedToBottom(true);
    scrollToBottom("smooth");
    try {
      await onSend(text, filesToSend);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    // 中文等 IME 输入：选词/上屏时的 Enter 不应发送消息
    if (e.nativeEvent.isComposing) return;
    if ((e as React.KeyboardEvent<HTMLTextAreaElement> & { keyCode?: number }).keyCode === 229)
      return;
    e.preventDefault();
    void handleSend();
  };

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setPinnedToBottom(isNearBottom(e.currentTarget));
  }, []);

  const beginEditMessage = useCallback((message: ChatMessageItem) => {
    setEditingMessageId(message.id);
    setEditingValue(message.content);
  }, []);

  const cancelEditMessage = useCallback(() => {
    setEditingMessageId(null);
    setEditingValue("");
  }, []);

  const submitEditMessage = useCallback(
    async (message: ChatMessageItem) => {
      if (!onResendUserMessage) {
        return;
      }
      const nextContent = editingValue.trim();
      if (!nextContent) {
        return;
      }
      setMessageActionId(`edit-${message.id}`);
      try {
        await onResendUserMessage(message, nextContent);
        cancelEditMessage();
      } finally {
        setMessageActionId(null);
      }
    },
    [cancelEditMessage, editingValue, onResendUserMessage],
  );

  const regenerateAssistantMessage = useCallback(
    async (message: ChatMessageItem) => {
      if (!onRegenerateAssistantMessage) {
        return;
      }
      setMessageActionId(`regen-${message.id}`);
      try {
        await onRegenerateAssistantMessage(message);
      } finally {
        setMessageActionId(null);
      }
    },
    [onRegenerateAssistantMessage],
  );

  const copyMessage = useCallback(async (message: ChatMessageItem) => {
    try {
      const text = message.content.replace(NODE_REPORT_MARKER_RE, "");
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(message.id);
      window.setTimeout(() => {
        setCopiedMessageId((current) => (current === message.id ? null : current));
      }, 1200);
    } catch {
      // ignore copy failures in unsupported contexts
    }
  }, []);

  // 快捷操作胶囊：常驻在输入框正上方（无论是否已有消息）。
  const renderQuickActions = () =>
    disabled ? null : (
      <div className="scrollbar-none mb-2.5 flex flex-nowrap items-center gap-2 overflow-x-auto">
        {QUICK_ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.label}
              type="button"
              disabled={sending}
              onClick={() => void handleSend(action.prompt)}
              className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-[#E7ECF3] bg-white py-1.5 pl-1.5 pr-3.5 text-[13px] font-medium text-[#3D4658] shadow-[0_2px_8px_rgba(31,42,68,0.04)] transition-all hover:border-[#4C84FF]/40 hover:shadow-[0_8px_20px_rgba(76,132,255,0.12)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                style={{
                  backgroundColor: action.iconBg,
                  color: action.iconColor,
                }}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              {action.label}
            </button>
          );
        })}
      </div>
    );

  const renderComposer = (mode: "empty" | "docked") => (
    <div
      className={cn(
        "mx-auto w-full",
        mode === "empty" ? "max-w-[860px]" : "max-w-[920px]",
      )}
    >
      {renderQuickActions()}
      <div
        className={cn(
          "rounded-[30px] border bg-white shadow-[0_22px_56px_rgba(31,42,68,0.08)] transition-all duration-200",
          draggingOver
            ? "border-[#4C84FF] bg-[#F8FAFF]"
            : "border-[#E7ECF3] focus-within:border-[#4C84FF] focus-within:shadow-[0_22px_56px_rgba(76,132,255,0.16)]",
          mode === "empty" ? "p-4 sm:p-5" : "p-3.5 sm:p-4",
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_FILE_EXTENSIONS}
          className="hidden"
          onChange={handleFileInputChange}
        />

        {pendingFiles.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {pendingFiles.map((file, idx) => {
              const previewUrl = imagePreviews[file.name + file.size];
              return (
                <div
                  key={`${file.name}-${file.size}-${idx}`}
                  className="group/file relative flex items-center gap-2 rounded-2xl border border-[#E7ECF3] bg-[#F8FAFF] px-3 py-2"
                >
                  {previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={previewUrl}
                      alt={file.name}
                      className="h-10 w-10 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#EFF4FF]">
                      <FileText className="h-5 w-5 text-[#4C84FF]" />
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="max-w-[140px] truncate text-xs font-medium text-slate-100">
                      {file.name}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {formatFileSize(file.size)}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-[#E7ECF3] bg-white text-slate-400 opacity-0 shadow-sm transition hover:text-slate-200 group-hover/file:opacity-100"
                    onClick={() => removeFile(idx)}
                    aria-label="移除文件"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <Textarea
          ref={composerRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? disabledReason ?? "对话已结束"
              : hasMessages
                ? "继续追问..."
                : "有问题，尽管问"
          }
          disabled={disabled || sending}
          rows={1}
          className="min-h-[30px] resize-none border-0 bg-transparent px-1 py-0.5 text-[15px] leading-6 text-slate-100 shadow-none outline-none ring-0 focus:border-0 focus:ring-0 focus-visible:border-0 focus-visible:ring-0 disabled:opacity-60"
        />

        <div className="mt-2 flex items-center justify-between gap-3 border-t border-[#E7ECF3] pt-3">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200 disabled:opacity-40"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled || sending || pendingFiles.length >= MAX_FILES_PER_MESSAGE}
              aria-label="添加附件"
              title={`添加附件（最多 ${MAX_FILES_PER_MESSAGE} 个）`}
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <p className="min-w-0 truncate text-xs text-slate-500">
              {disabled ? (
                disabledReason ?? "当前会话已结束"
              ) : isStreaming ? (
                "正在生成，可随时停止当前回复"
              ) : (
                // 键盘快捷键提示仅在带物理键盘的宽屏显示；
                // 手机端无 Enter/Shift 键，隐藏这条避免误导。
                <span className="hidden sm:inline">
                  Enter 发送，Shift + Enter 换行
                </span>
              )}
            </p>
          </div>

          {isStreaming && onStopStreaming ? (
            <Button
              type="button"
              onClick={onStopStreaming}
              size="icon"
              variant="secondary"
              className="h-11 w-11 rounded-full border border-amber-300/24 bg-amber-300/12 text-amber-100 hover:bg-amber-300/18"
              aria-label="停止生成当前回复"
              title="停止生成当前回复（已输出内容会保留为草稿，不会结束整个会话）"
            >
              <Square className="h-4 w-4 fill-current" />
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => void handleSend()}
              disabled={disabled || sending || (!input.trim() && pendingFiles.length === 0)}
              className="h-10 gap-1.5 rounded-full border border-transparent bg-[#4A86E8] px-5 text-sm font-medium text-white shadow-[0_8px_22px_rgba(74,134,232,0.25)] hover:bg-[#3F76EE] disabled:border-[#E7ECF3] disabled:bg-[#EFF4FF] disabled:text-slate-500 disabled:shadow-none"
              aria-label="发送消息"
            >
              {sending ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  发送
                </>
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div
      className={cn(
        "relative flex min-h-0 w-full flex-1",
        className,
      )}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className={cn(
            "scrollbar-subtle absolute inset-0 overflow-y-auto overscroll-contain",
            hasMessages ? "px-5 py-8 sm:px-8" : "px-4 py-6 sm:px-6",
          )}
        >
          {showCenteredEmptyState ? (
            <div className="flex min-h-full items-center justify-center py-10 sm:py-14">
              <div className="w-full max-w-[960px]">
                <div className="mx-auto max-w-[760px] text-center">
                  <h2 className="text-[clamp(2.25rem,5vw,3.6rem)] font-semibold tracking-tight text-slate-50">
                    有什么想聊的？
                  </h2>
                </div>

                <div className="mt-8 sm:mt-10">{renderComposer("empty")}</div>

                {!disabled && (
                  <div className="mx-auto mt-5 max-w-[620px] rounded-xl border border-dashed border-[#CBD9F2] bg-[#F6F9FE] px-4 py-2.5 text-center text-xs leading-5 text-[#8A97AE]">
                    {QUICK_EXAMPLE}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-[920px] space-y-10 pb-6">
              {messages.map((msg, index) => {
                const isUser = msg.role === "user";
                const isEditingMessage = editingMessageId === msg.id;
                const isActionPending =
                  messageActionId === `edit-${msg.id}` ||
                  messageActionId === `regen-${msg.id}`;
                const showEditAction =
                  isUser && Boolean(onResendUserMessage) && !isStreaming;
                const showRegenerateAction =
                  msg.role === "assistant" &&
                  Boolean(onRegenerateAssistantMessage) &&
                  msg.generationState !== "streaming" &&
                  !isStreaming;
                const messagePlan =
                  msg.role === "assistant"
                    ? msg.plan ?? extractChatPlanFromToolCalls(msg.tool_calls_json)
                    : undefined;
                const canCopyMessage = Boolean(msg.content.trim());
                const showFeedbackAction =
                  msg.role === "assistant" &&
                  Boolean(onSubmitFeedback) &&
                  !msg.localOnly &&
                  msg.generationState !== "streaming" &&
                  canCopyMessage;
                const showActionBar =
                  !isEditingMessage &&
                  (isUser
                    ? canCopyMessage || showEditAction
                    : canCopyMessage ||
                      showRegenerateAction ||
                      showFeedbackAction ||
                      msg.generationState === "stopped");

                return (
                  <div key={msg.id} className="group/message space-y-3">
                    {shouldShowTimestamp(msg, messages[index - 1]) && (
                      <div className="flex justify-center">
                        <span className="rounded-full bg-[#F8FAFD] px-3 py-1 text-[11px] text-slate-500">
                          {formatMessageTimestamp(msg.created_at)}
                        </span>
                      </div>
                    )}

                    <div
                      className={cn(
                        "flex w-full",
                        isUser ? "justify-end" : "justify-start",
                      )}
                    >
                      <div
                        className={cn(
                          "min-w-0",
                          isUser ? "max-w-[78%]" : "w-full",
                        )}
                      >
                        {isUser ? (
                          <UserMessageBubble
                            content={msg.content}
                            onOpenArtifact={openArtifact}
                          />
                        ) : (
                          <div className="max-w-[860px] text-[15px] leading-7 text-slate-100">
                            <AssistantMessageContent
                              content={msg.content}
                              generationState={msg.generationState}
                              onOpenArtifact={openArtifact}
                              plan={messagePlan}
                              actions={msg.actions}
                              thinking={msg.thinking}
                            />
                          </div>
                        )}

                        {showActionBar && (
                            <div
                              className={cn(
                                "mt-2 flex flex-wrap items-center gap-1.5",
                                isUser
                                  ? "justify-end pr-1"
                                  : "justify-start",
                              )}
                            >
                              {isUser ? (
                                <div className="pointer-events-none flex items-center gap-1 opacity-0 transition-opacity duration-150 group-hover/message:pointer-events-auto group-hover/message:opacity-100">
                                  <button
                                    type="button"
                                    className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
                                    onClick={() => void copyMessage(msg)}
                                    disabled={loading || sending || !canCopyMessage}
                                    aria-label="复制消息"
                                    title="复制"
                                  >
                                    {copiedMessageId === msg.id ? (
                                      <Check className="h-4 w-4" />
                                    ) : (
                                      <Copy className="h-4 w-4" />
                                    )}
                                  </button>
                                  {showEditAction && (
                                    <button
                                      type="button"
                                      className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
                                      onClick={() => beginEditMessage(msg)}
                                      disabled={loading || sending || isActionPending}
                                      aria-label="编辑消息"
                                      title="编辑"
                                    >
                                      <PencilLine className="h-4 w-4" />
                                    </button>
                                  )}
                                </div>
                              ) : (
                                <div className="flex flex-wrap items-start gap-1">
                                  <button
                                    type="button"
                                    className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
                                    onClick={() => void copyMessage(msg)}
                                    disabled={loading || sending || !canCopyMessage}
                                    aria-label="复制消息"
                                    title="复制"
                                  >
                                    {copiedMessageId === msg.id ? (
                                      <Check className="h-4 w-4" />
                                    ) : (
                                      <Copy className="h-4 w-4" />
                                    )}
                                  </button>
                                  {showRegenerateAction && (
                                    <button
                                      type="button"
                                      className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-[#F3F6FB] hover:text-slate-200"
                                      onClick={() =>
                                        void regenerateAssistantMessage(msg)
                                      }
                                      disabled={loading || sending || isActionPending}
                                      aria-label="重新生成"
                                      title="重新生成"
                                    >
                                      {isActionPending ? (
                                        <LoaderCircle className="h-4 w-4 animate-spin" />
                                      ) : (
                                        <RefreshCcw className="h-4 w-4" />
                                      )}
                                    </button>
                                  )}
                                  {showFeedbackAction && onSubmitFeedback && (
                                    <MessageFeedback
                                      message={msg}
                                      disabled={loading || sending}
                                      onSubmitFeedback={onSubmitFeedback}
                                    />
                                  )}
                                </div>
                              )}
                              {msg.generationState === "stopped" && (
                                <span className="text-[11px] text-amber-300/80">
                                  已暂停
                                </span>
                              )}
                            </div>
                          )}

                        {isEditingMessage && (
                          <div className="mt-3 ml-auto w-full rounded-[26px] border border-[#E7ECF3] bg-white p-4 shadow-[0_12px_30px_rgba(31,42,68,0.06)]">
                            <Textarea
                              value={editingValue}
                              onChange={(event) =>
                                setEditingValue(event.target.value)
                              }
                              rows={4}
                              className="min-h-[112px] resize-none border-0 bg-transparent px-0 py-0 text-sm text-slate-100 shadow-none outline-none ring-0 focus:border-0 focus:ring-0"
                            />
                            <div className="mt-3 flex items-center justify-end gap-2 border-t border-[#E7ECF3] pt-3">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={cancelEditMessage}
                                disabled={isActionPending}
                              >
                                <X className="h-3.5 w-3.5" />
                                取消
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                onClick={() => void submitEditMessage(msg)}
                                disabled={
                                  isActionPending || !editingValue.trim()
                                }
                              >
                                {isActionPending ? (
                                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Send className="h-3.5 w-3.5" />
                                )}
                                重新发送
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}

              {messageListFooterSlot && (
                <div className="flex justify-start">
                  <div className="w-full max-w-[860px]">{messageListFooterSlot}</div>
                </div>
              )}

              {(sending || loading) &&
                !messages.some((m) => m.generationState === "streaming") && (
                  <div className="flex justify-start">
                    <div className="max-w-[860px] py-1 text-[15px] leading-7 text-slate-400">
                      <TypingDots />
                    </div>
                  </div>
                )}
            </div>
          )}
        </div>

        {!pinnedToBottom && hasMessages && (
          <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex justify-center px-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="pointer-events-auto rounded-full border border-[#E7ECF3] bg-white px-3 text-slate-200 shadow-[0_12px_30px_rgba(31,42,68,0.10)] backdrop-blur"
              onClick={() => {
                setPinnedToBottom(true);
                scrollToBottom("smooth");
              }}
            >
              查看最新消息
              <ChevronDown className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>

      {hasMessages && (
        <div className="shrink-0 px-5 pb-5 pt-2 sm:px-8">
          {renderComposer("docked")}
        </div>
      )}
      </div>

      <ArtifactPanel
        artifact={activeArtifact}
        visible={artifactVisible}
        onClose={closeArtifact}
      />
    </div>
  );
}
