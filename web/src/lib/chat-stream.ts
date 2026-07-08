/** 解析聊天 SSE（POST + text/event-stream） */

export type ChatPlanState = "todo" | "in_progress" | "done" | "abandoned";

export type ChatPlanTask = {
  index: number;
  name: string;
  description: string;
  expected_outcome: string;
  outcome: string | null;
  state: ChatPlanState;
};

export type ChatPlanPayload = {
  id: string;
  name: string;
  description: string;
  expected_outcome: string;
  outcome: string | null;
  state: ChatPlanState;
  subtasks: ChatPlanTask[];
};

export type ChatToolCall = {
  id?: string;
  name?: string;
  arguments?: Record<string, unknown> | null;
};

export type ChatToolResult = {
  id?: string;
  tool_name?: string;
  is_error?: boolean;
  output?: string;
};

export type ChatStreamHandlers = {
  onDelta: (text: string) => void;
  onThinking?: (text: string) => void;
  onToolCall?: (tool: ChatToolCall) => void;
  onToolResult?: (tool: ChatToolResult) => void;
  onPlan?: (plan: ChatPlanPayload) => void;
  onDone: (payload: unknown) => void;
  onError: (message: string) => void;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPlanState(value: unknown): value is ChatPlanState {
  return (
    value === "todo" ||
    value === "in_progress" ||
    value === "done" ||
    value === "abandoned"
  );
}

function isChatPlanTask(value: unknown): value is ChatPlanTask {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.index === "number" &&
    typeof value.name === "string" &&
    typeof value.description === "string" &&
    typeof value.expected_outcome === "string" &&
    (typeof value.outcome === "string" || value.outcome === null) &&
    isPlanState(value.state)
  );
}

export function isChatPlanPayload(value: unknown): value is ChatPlanPayload {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.description === "string" &&
    typeof value.expected_outcome === "string" &&
    (typeof value.outcome === "string" || value.outcome === null) &&
    isPlanState(value.state) &&
    Array.isArray(value.subtasks) &&
    value.subtasks.every(isChatPlanTask)
  );
}

export function extractChatPlanFromToolCalls(
  toolCalls: unknown,
): ChatPlanPayload | undefined {
  if (!Array.isArray(toolCalls)) {
    return undefined;
  }
  for (const item of toolCalls) {
    if (
      isRecord(item) &&
      item.type === "agent_plan" &&
      isChatPlanPayload(item.plan)
    ) {
      return item.plan;
    }
  }
  return undefined;
}

/** Action timeline 条目：一次工具调用 + 其结果合成一项。 */
export type ChatAgentAction = {
  id?: string;
  name?: string;
  arguments?: Record<string, unknown> | null;
  output?: string;
  is_error?: boolean;
  status: "running" | "ok" | "error";
};

export function extractChatActionsFromToolCalls(
  toolCalls: unknown,
): ChatAgentAction[] {
  if (!Array.isArray(toolCalls)) {
    return [];
  }
  for (const item of toolCalls) {
    if (
      isRecord(item) &&
      item.type === "agent_actions" &&
      Array.isArray(item.actions)
    ) {
      const actions: ChatAgentAction[] = [];
      const indexById = new Map<string, number>();
      for (const a of item.actions as unknown[]) {
        if (!isRecord(a)) continue;
        const id = typeof a.id === "string" ? a.id : undefined;
        if (a.type === "result") {
          const idx = id ? indexById.get(id) : undefined;
          if (idx !== undefined) {
            actions[idx].output = typeof a.output === "string" ? a.output : undefined;
            actions[idx].is_error = Boolean(a.is_error);
            actions[idx].status = a.is_error ? "error" : "ok";
          } else {
            actions.push({
              id,
              name: typeof a.name === "string" ? a.name : undefined,
              output: typeof a.output === "string" ? a.output : undefined,
              is_error: Boolean(a.is_error),
              status: a.is_error ? "error" : "ok",
            });
          }
        } else {
          actions.push({
            id,
            name: typeof a.name === "string" ? a.name : undefined,
            arguments: isRecord(a.arguments)
              ? (a.arguments as Record<string, unknown>)
              : null,
            status: "running",
          });
          if (id) indexById.set(id, actions.length - 1);
        }
      }
      return actions;
    }
  }
  return [];
}

export async function postChatMessageStream(
  url: string,
  content: string,
  headers: HeadersInit,
  handlers: ChatStreamHandlers,
  init?: { signal?: AbortSignal },
): Promise<void> {
  const h = new Headers(headers);
  h.set("Content-Type", "application/json");

  const res = await fetch(url, {
    method: "POST",
    headers: h,
    body: JSON.stringify({ content }),
    credentials: "include",
    cache: "no-store",
    signal: init?.signal,
  });

  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // ignore
    }
    handlers.onError(detail);
    return;
  }

  if (!res.body) {
    handlers.onError("无响应体");
    return;
  }

  const reader = res.body.getReader();
  const signal = init?.signal;
  const onAbort = () => {
    void reader.cancel();
  };
  if (signal) {
    if (signal.aborted) {
      onAbort();
      throw new DOMException("The operation was aborted.", "AbortError");
    }
    signal.addEventListener("abort", onAbort, { once: true });
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      while (true) {
        const sep = buffer.indexOf("\n\n");
        if (sep === -1) {
          break;
        }
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const line = raw.startsWith("data:") ? raw.slice(5).trim() : raw.trim();
        if (!line) {
          continue;
        }
        let obj: {
          type?: string;
          text?: string;
          plan?: unknown;
          tool?: unknown;
          message?: string;
          payload?: unknown;
        };
        try {
          obj = JSON.parse(line) as typeof obj;
        } catch {
          continue;
        }
        if (obj.type === "delta" && typeof obj.text === "string") {
          handlers.onDelta(obj.text);
        } else if (obj.type === "thinking" && typeof obj.text === "string") {
          handlers.onThinking?.(obj.text);
        } else if (obj.type === "tool_call" && isRecord(obj.tool)) {
          handlers.onToolCall?.(obj.tool as ChatToolCall);
        } else if (obj.type === "tool_result" && isRecord(obj.tool)) {
          handlers.onToolResult?.(obj.tool as ChatToolResult);
        } else if (obj.type === "plan" && isChatPlanPayload(obj.plan)) {
          handlers.onPlan?.(obj.plan);
        } else if (obj.type === "done") {
          handlers.onDone(obj.payload);
        } else if (obj.type === "error") {
          handlers.onError(
            typeof obj.message === "string" ? obj.message : "未知错误",
          );
        }
      }
    }
  } finally {
    if (signal) {
      signal.removeEventListener("abort", onAbort);
    }
  }
}
