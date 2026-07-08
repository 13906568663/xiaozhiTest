"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  LoaderCircle,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import {
  AlertDialog,
  AlertDialogCancelButton,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { API_BASE_URL, buildApiHeaders, requestJson } from "@/lib/api-fetch";
import {
  extractChatActionsFromToolCalls,
  extractChatPlanFromToolCalls,
  postChatMessageStream,
  type ChatAgentAction,
  type ChatPlanPayload,
} from "@/lib/chat-stream";
import { cn } from "@/lib/utils";
import { ChatWidget, type ChatMessageItem } from "@/components/chatbot/chat-widget";

type ChatbotInfo = {
  id: string;
  name: string;
  description: string | null;
  session_count: number;
  status?: "active" | "inactive";
};

type SessionSummary = {
  id: string;
  chatbot_id: string;
  status: string;
  title: string;
  last_message_preview: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
};

type SessionDetail = {
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type ApiChatMessage = {
  id: string;
  role: string;
  content: string;
  seq: number;
  created_at: string;
  tool_calls_json?: Array<Record<string, unknown>>;
};

type ChatResponse = {
  message: ChatMessageItem;
  session_status: string;
  goal_achieved: boolean;
  goal_result: Record<string, unknown> | null;
};

type SessionDeleteResponse = {
  deleted: boolean;
  session_id: string;
};

type StreamRequestState = {
  controller: AbortController;
  sessionId: string;
  userId: string;
  assistantId: string;
  userContent: string;
  baseMessages: ChatMessageItem[];
};

type ChatTestPageProps = {
  paramsPromise: Promise<{ id: string }>;
};

type SessionGroup = {
  label: string;
  items: SessionSummary[];
};

const EMPTY_SESSION_TITLE = "新对话";
const EMPTY_SESSION_PREVIEW = "还没有消息，开始打一声招呼吧。";

function mapMessages(items: ApiChatMessage[]): ChatMessageItem[] {
  return items.map((message) => {
    const actions = extractChatActionsFromToolCalls(message.tool_calls_json);
    return {
      id: message.id,
      role: message.role,
      content: message.content,
      seq: message.seq,
      created_at: message.created_at,
      tool_calls_json: message.tool_calls_json,
      plan: extractChatPlanFromToolCalls(message.tool_calls_json),
      actions: actions.length > 0 ? actions : undefined,
    };
  });
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateText(
  value: string | null | undefined,
  maxLength: number,
): string {
  const normalized = normalizeText(value);
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

function buildLocalSessionSummary(session: SessionDetail): SessionSummary {
  return {
    id: session.id,
    chatbot_id: "",
    status: session.status,
    title: EMPTY_SESSION_TITLE,
    last_message_preview: EMPTY_SESSION_PREVIEW,
    message_count: 0,
    created_at: session.created_at,
    updated_at: session.updated_at,
  };
}

function committedMessages(items: ChatMessageItem[]): ChatMessageItem[] {
  return items.filter((item) => !item.localOnly);
}

function buildSummaryFromMessages(
  session: SessionDetail,
  chatbotId: string,
  items: ChatMessageItem[],
  fallbackTitle?: string,
): SessionSummary {
  const firstUserMessage = items.find((item) => item.role === "user")?.content;
  const lastMessage = items[items.length - 1]?.content;

  return {
    ...buildLocalSessionSummary(session),
    chatbot_id: chatbotId,
    title:
      truncateText(firstUserMessage, 40) ||
      truncateText(fallbackTitle, 40) ||
      EMPTY_SESSION_TITLE,
    last_message_preview: truncateText(lastMessage, 72) || null,
    message_count: items.length,
  };
}

function findPreviousUserMessage(
  items: ChatMessageItem[],
  target: ChatMessageItem,
): ChatMessageItem | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const current = items[index];
    if (!current || current.seq >= target.seq) {
      continue;
    }
    if (current.role === "user") {
      return current;
    }
  }
  return null;
}

function moveSessionToFront(
  sessions: SessionSummary[],
  next: SessionSummary,
): SessionSummary[] {
  return [next, ...sessions.filter((item) => item.id !== next.id)];
}

function formatSessionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const now = new Date();
  const isSameYear = date.getFullYear() === now.getFullYear();
  const isSameDay =
    isSameYear &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isSameDay) {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  return new Intl.DateTimeFormat("zh-CN", {
    ...(isSameYear ? {} : { year: "2-digit" }),
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function groupSessionsByRecency(sessions: SessionSummary[]): SessionGroup[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const today = startOfToday.getTime();
  const sevenDaysAgo = today - 6 * 24 * 60 * 60 * 1000;

  const buckets = new Map<string, SessionSummary[]>();

  sessions.forEach((session) => {
    const updatedAt = new Date(session.updated_at).getTime();
    const label =
      updatedAt >= today
        ? "今天"
        : updatedAt >= sevenDaysAgo
          ? "最近 7 天"
          : "更早";
    const current = buckets.get(label) ?? [];
    current.push(session);
    buckets.set(label, current);
  });

  return ["今天", "最近 7 天", "更早"]
    .map((label) => ({
      label,
      items: buckets.get(label) ?? [],
    }))
    .filter((group) => group.items.length > 0);
}

function sessionStatusLabel(status: string): string {
  if (status === "active") {
    return "进行中";
  }
  if (status === "completed") {
    return "已完成";
  }
  return "已过期";
}

function sessionStatusDotClass(status: string): string {
  if (status === "active") {
    return "bg-[#35C58A]";
  }
  if (status === "completed") {
    return "bg-[#4C84FF]";
  }
  return "bg-[#F56C6C]";
}

export function ChatTestPage({ paramsPromise }: ChatTestPageProps) {
  const params = use(paramsPromise);
  const chatbotId = params.id;

  const [bot, setBot] = useState<ChatbotInfo | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [sessionStatus, setSessionStatus] = useState<string>("active");
  const [loading, setLoading] = useState(true);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sessionQuery, setSessionQuery] = useState("");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sessionMenuId, setSessionMenuId] = useState<string | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renamingValue, setRenamingValue] = useState("");
  const [sessionActionId, setSessionActionId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary | null>(null);
  const messagesRef = useRef<ChatMessageItem[]>([]);
  const activeStreamRef = useRef<StreamRequestState | null>(null);

  const selectedSession = useMemo(
    () => sessions.find((item) => item.id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  );

  const filteredSessions = useMemo(() => {
    const keyword = normalizeText(sessionQuery).toLowerCase();
    if (!keyword) {
      return sessions;
    }
    return sessions.filter((item) => {
      const haystack = [
        item.title,
        item.last_message_preview ?? "",
        sessionStatusLabel(item.status),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [sessionQuery, sessions]);

  const groupedSessions = useMemo(
    () => groupSessionsByRecency(filteredSessions),
    [filteredSessions],
  );
  const totalSessionCount = sessions.length;
  const hasConversation = messages.length > 0;
  const sidebarDescription = useMemo(() => {
    const name = normalizeText(bot?.name);
    const description = normalizeText(bot?.description);
    if (!description || description === name) {
      return null;
    }
    return bot?.description ?? null;
  }, [bot?.description, bot?.name]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    if (!sessionMenuId) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-session-menu-root='true']")) {
        return;
      }
      setSessionMenuId(null);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [sessionMenuId]);

  const loadSessionSummaries = useCallback(async (): Promise<SessionSummary[]> => {
    const query = new URLSearchParams({
      chatbot_id: chatbotId,
      limit: "50",
    });
    const data = await requestJson<SessionSummary[]>(
      `/chat/sessions?${query.toString()}`,
    );
    setSessions(data);
    return data;
  }, [chatbotId]);

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    const history = await requestJson<ApiChatMessage[]>(
      `/chat/sessions/${sessionId}/messages`,
    );
    setMessages(mapMessages(history));
  }, []);

  const openSession = useCallback(
    async (sessionId: string) => {
      if (!sessionId) {
        return;
      }

      setConversationLoading(true);
      setSendError(null);
      setSelectedSessionId(sessionId);
      setMobileSidebarOpen(false);
      setSessionMenuId(null);
      setRenamingSessionId(null);
      setRenamingValue("");
      setMessages([]);

      try {
        const sessionData = await requestJson<SessionDetail>(
          `/chat/sessions/${sessionId}`,
        );
        setSessionStatus(sessionData.status);
        await loadSessionMessages(sessionId);
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "加载会话内容失败。",
        );
      } finally {
        setConversationLoading(false);
      }
    },
    [loadSessionMessages],
  );

  const startNewChat = useCallback(async () => {
    if (streaming) {
      return;
    }

    setCreatingSession(true);
    setSendError(null);

    try {
      const sessionData = await requestJson<SessionDetail>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ chatbot_id: chatbotId }),
      });
      const localSummary = buildLocalSessionSummary(sessionData);
      setSessions((current) => moveSessionToFront(current, localSummary));
      setSelectedSessionId(sessionData.id);
      setSessionStatus(sessionData.status);
      setMessages([]);
      setMobileSidebarOpen(false);
      setSessionMenuId(null);
      setRenamingSessionId(null);
      setRenamingValue("");
    } catch (error) {
      setSendError(error instanceof Error ? error.message : "无法创建新会话。");
    } finally {
      setCreatingSession(false);
    }
  }, [chatbotId, streaming]);

  const beginRenameSession = useCallback((item: SessionSummary) => {
    setSessionMenuId(null);
    setRenamingSessionId(item.id);
    setRenamingValue(item.title === EMPTY_SESSION_TITLE ? "" : item.title);
  }, []);

  const cancelRenameSession = useCallback(() => {
    setRenamingSessionId(null);
    setRenamingValue("");
  }, []);

  const requestDeleteSession = useCallback((item: SessionSummary) => {
    setSessionMenuId(null);
    setDeleteTarget(item);
  }, []);

  const submitRenameSession = useCallback(
    async (sessionId: string) => {
      const trimmed = renamingValue.trim();
      if (!trimmed) {
        cancelRenameSession();
        return;
      }

      setSessionActionId(`rename-${sessionId}`);
      try {
        const updated = await requestJson<SessionSummary>(
          `/chat/sessions/${sessionId}`,
          {
            method: "PATCH",
            body: JSON.stringify({ title: trimmed }),
          },
        );
        setSessions((current) =>
          current.map((item) => (item.id === sessionId ? updated : item)),
        );
        cancelRenameSession();
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "重命名会话失败。",
        );
      } finally {
        setSessionActionId(null);
      }
    },
    [cancelRenameSession, renamingValue],
  );

  const handleDeleteSession = useCallback(
    async () => {
      if (!deleteTarget || streaming || conversationLoading) {
        return;
      }

      const sessionId = deleteTarget.id;
      setSessionActionId(`delete-${sessionId}`);
      try {
        await requestJson<SessionDeleteResponse>(`/chat/sessions/${sessionId}`, {
          method: "DELETE",
        });
        setDeleteTarget(null);
        const remaining = sessions.filter((item) => item.id !== sessionId);
        setSessions(remaining);

        if (selectedSessionId === sessionId) {
          setMessages([]);
          if (remaining.length > 0) {
            await openSession(remaining[0].id);
          } else {
            await startNewChat();
          }
        }
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "删除会话失败。",
        );
      } finally {
        setSessionActionId(null);
      }
    },
    [
      conversationLoading,
      deleteTarget,
      openSession,
      selectedSessionId,
      sessions,
      startNewChat,
      streaming,
    ],
  );

  const refreshSelectedSessionSummary = useCallback(
    async (sessionId: string) => {
      const latest = await loadSessionSummaries();
      const matched = latest.find((item) => item.id === sessionId);
      if (matched) {
        setSessionStatus(matched.status);
      }
    },
    [loadSessionSummaries],
  );

  const initChat = useCallback(async () => {
    setLoading(true);
    setPageError(null);

    try {
      const botData = await requestJson<ChatbotInfo>(`/chatbots/${chatbotId}`);
      setBot(botData);

      if (botData.status === "inactive") {
        setPageError(
          "该机器人当前为停用状态，无法使用对话台。请在「对话配置」中编辑并打开「启用机器人」后再试。",
        );
        return;
      }

      const sessionItems = await loadSessionSummaries();
      const initialSessionId = sessionItems[0]?.id ?? null;

      if (initialSessionId) {
        await openSession(initialSessionId);
      } else {
        const sessionData = await requestJson<SessionDetail>("/chat/sessions", {
          method: "POST",
          body: JSON.stringify({ chatbot_id: chatbotId }),
        });
        const localSummary = buildLocalSessionSummary(sessionData);
        setSessions([localSummary]);
        setSelectedSessionId(sessionData.id);
        setSessionStatus(sessionData.status);
        setMessages([]);
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "初始化聊天失败。");
    } finally {
      setLoading(false);
    }
  }, [chatbotId, loadSessionSummaries, openSession]);

  useEffect(() => {
    void initChat();
  }, [initChat]);

  const branchSession = useCallback(
    async (sessionId: string, beforeSeq?: number): Promise<SessionDetail> => {
      return requestJson<SessionDetail>(`/chat/sessions/${sessionId}/branch`, {
        method: "POST",
        body: JSON.stringify(
          beforeSeq != null ? { before_seq: beforeSeq } : {},
        ),
      });
    },
    [],
  );

  const sendMessageToSession = useCallback(
    async ({
      sessionId,
      content,
      baseMessages,
    }: {
      sessionId: string;
      content: string;
      baseMessages?: ChatMessageItem[];
    }) => {
      const stableMessages = committedMessages(baseMessages ?? messagesRef.current);
      const createdAt = new Date().toISOString();
      const lastSeq = stableMessages[stableMessages.length - 1]?.seq ?? 0;
      const optimisticUserId = `temp-user-${Date.now()}`;
      const streamAssistId = `stream-assist-${Date.now()}`;
      const controller = new AbortController();

      activeStreamRef.current = {
        controller,
        sessionId,
        userId: optimisticUserId,
        assistantId: streamAssistId,
        userContent: content,
        baseMessages: stableMessages,
      };

      setStreaming(true);
      setSendError(null);
      setSelectedSessionId(sessionId);
      setSessionStatus("active");
      setMessages([
        ...stableMessages,
        {
          id: optimisticUserId,
          role: "user",
          content,
          seq: lastSeq + 1,
          created_at: createdAt,
          localOnly: true,
        },
        {
          id: streamAssistId,
          role: "assistant",
          content: "",
          seq: lastSeq + 2,
          created_at: createdAt,
          localOnly: true,
          generationState: "streaming",
        },
      ]);

      const streamState = {
        error: null as string | null,
        payload: null as ChatResponse | null,
        plan: null as ChatPlanPayload | null,
      };

      try {
        await postChatMessageStream(
          `${API_BASE_URL}/chat/sessions/${sessionId}/messages/stream`,
          content,
          buildApiHeaders(undefined, true),
          {
            onDelta: (text) => {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === streamAssistId
                    ? {
                        ...message,
                        content: message.content + text,
                      }
                    : message,
                ),
              );
            },
            onThinking: (text) => {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === streamAssistId
                    ? {
                        ...message,
                        thinking: (message.thinking ?? "") + text,
                      }
                    : message,
                ),
              );
            },
            onToolCall: (tool) => {
              setMessages((prev) =>
                prev.map((message) => {
                  if (message.id !== streamAssistId) return message;
                  const actions = message.actions ? [...message.actions] : [];
                  actions.push({
                    id: tool.id,
                    name: tool.name,
                    arguments: tool.arguments ?? null,
                    status: "running",
                  });
                  return { ...message, actions };
                }),
              );
            },
            onToolResult: (tool) => {
              setMessages((prev) =>
                prev.map((message) => {
                  if (message.id !== streamAssistId) return message;
                  const actions = message.actions ? [...message.actions] : [];
                  const idx = actions.findIndex(
                    (a) => a.id && a.id === tool.id,
                  );
                  const next: ChatAgentAction = {
                    id: tool.id,
                    name: tool.tool_name,
                    output: tool.output,
                    is_error: tool.is_error,
                    status: tool.is_error ? "error" : "ok",
                  };
                  if (idx >= 0) {
                    actions[idx] = { ...actions[idx], ...next };
                  } else {
                    actions.push(next);
                  }
                  return { ...message, actions };
                }),
              );
            },
            onPlan: (plan) => {
              streamState.plan = plan;
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === streamAssistId
                    ? {
                        ...message,
                        plan,
                        tool_calls_json: [{ type: "agent_plan", plan }],
                      }
                    : message,
                ),
              );
            },
            onDone: (payload) => {
              streamState.payload = payload as ChatResponse;
            },
            onError: (message) => {
              streamState.error = message;
            },
          },
          { signal: controller.signal },
        );
      } catch (error) {
        if (controller.signal.aborted) {
          const pausedAt = new Date().toISOString();
          setMessages((prev) =>
            prev.map((message) => {
              if (message.id === optimisticUserId) {
                return {
                  ...message,
                  id: `draft-user-${Date.now()}`,
                  localOnly: true,
                };
              }
              if (message.id === streamAssistId) {
                return {
                  ...message,
                  id: `draft-assist-${Date.now()}`,
                  created_at: pausedAt,
                  localOnly: true,
                  generationState: "stopped",
                };
              }
              return message;
            }),
          );
          return;
        }

        setMessages(stableMessages);
        setSendError(error instanceof Error ? error.message : "网络错误。");
        return;
      } finally {
        if (activeStreamRef.current?.controller === controller) {
          activeStreamRef.current = null;
        }
        setStreaming(false);
      }

      if (streamState.error) {
        setMessages(stableMessages);
        setSendError(streamState.error);
        return;
      }

      const response = streamState.payload;
      if (!response) {
        setMessages(stableMessages);
        setSendError("未收到完整回复。");
        return;
      }

      const responsePlan =
        streamState.plan ??
        extractChatPlanFromToolCalls(response.message.tool_calls_json);
      const responseActions = extractChatActionsFromToolCalls(
        response.message.tool_calls_json,
      );
      const assistantMessage: ChatMessageItem = {
        ...response.message,
        ...(responsePlan ? { plan: responsePlan } : {}),
        ...(responseActions.length > 0 ? { actions: responseActions } : {}),
      };

      setMessages([
        ...stableMessages,
        {
          id: `user-${response.message.seq - 1}`,
          role: "user",
          content,
          seq: response.message.seq - 1,
          created_at: response.message.created_at,
        },
        assistantMessage,
      ]);

      setSessionStatus(response.session_status);
      setSessions((current) => {
        const existing = current.find((item) => item.id === sessionId);
        const derivedTitle = truncateText(content, 40);
        const derivedPreview =
          truncateText(response.message.content, 72) ||
          truncateText(content, 72) ||
          null;
        const updatedSummary: SessionSummary = {
          ...(existing ?? {
            id: sessionId,
            chatbot_id: chatbotId,
            status: response.session_status,
            title: derivedTitle || EMPTY_SESSION_TITLE,
            last_message_preview: derivedPreview,
            message_count: stableMessages.length + 2,
            created_at: response.message.created_at,
            updated_at: response.message.created_at,
          }),
          status: response.session_status,
          title:
            existing?.message_count === 0
              ? derivedTitle || existing?.title || EMPTY_SESSION_TITLE
              : existing?.title || derivedTitle || EMPTY_SESSION_TITLE,
          last_message_preview:
            derivedPreview || existing?.last_message_preview || null,
          message_count: stableMessages.length + 2,
          updated_at: response.message.created_at,
        };
        return moveSessionToFront(current, updatedSummary);
      });

      await refreshSelectedSessionSummary(sessionId);
    },
    [chatbotId, refreshSelectedSessionSummary],
  );

  const uploadAndCompose = useCallback(
    async (text: string, files?: File[]): Promise<string> => {
      if (!files || files.length === 0) return text;

      const parts: string[] = [];
      if (text) parts.push(text);

      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        const result = await requestJson<{
          file_name: string;
          file_size: number;
          content_type: "document" | "image";
          parsed_text?: string | null;
          data_url?: string | null;
          file_data_url?: string | null;
        }>("/chat/upload", { method: "POST", body: formData });

        if (result.content_type === "image" && result.data_url) {
          parts.push(`\n\n![${result.file_name}](${result.data_url})`);
        } else if (result.content_type === "document" && result.parsed_text) {
          parts.push(
            `\n\n---\n[文件: ${result.file_name}]\n${result.parsed_text}\n---`,
          );
          if (result.file_data_url) {
            parts.push(
              `\n\n[文件数据:${result.file_name}](${result.file_data_url})`,
            );
          }
        }
      }

      return parts.join("");
    },
    [],
  );

  const handleSend = useCallback(
    async (content: string, files?: File[]) => {
      if (!selectedSessionId) {
        return;
      }
      try {
        const composed = await uploadAndCompose(content, files);
        if (!composed.trim()) return;
        await sendMessageToSession({
          sessionId: selectedSessionId,
          content: composed,
        });
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "文件上传失败。",
        );
      }
    },
    [selectedSessionId, sendMessageToSession, uploadAndCompose],
  );

  const handleStopStreaming = useCallback(() => {
    activeStreamRef.current?.controller.abort();
  }, []);

  const handleRegenerateAssistant = useCallback(
    async (message: ChatMessageItem) => {
      if (!selectedSessionId || streaming) {
        return;
      }
      setSendError(null);

      try {
        const currentMessages = messagesRef.current;
        const userMessage = findPreviousUserMessage(currentMessages, message);
        if (!userMessage) {
          setSendError("未找到对应的用户消息，无法重新生成。");
          return;
        }

        const isDraftAssistant = Boolean(message.localOnly);
        if (isDraftAssistant) {
          const baseMessages = committedMessages(currentMessages);
          await sendMessageToSession({
            sessionId: selectedSessionId,
            content: userMessage.content,
            baseMessages,
          });
          return;
        }

        const prefixMessages = committedMessages(currentMessages).filter(
          (item) => item.seq < userMessage.seq,
        );
        const branchedSession = await branchSession(
          selectedSessionId,
          userMessage.seq,
        );
        const localSummary = buildSummaryFromMessages(
          branchedSession,
          chatbotId,
          prefixMessages,
          userMessage.content,
        );

        setSessions((current) => moveSessionToFront(current, localSummary));
        setSelectedSessionId(branchedSession.id);
        setSessionStatus(branchedSession.status);
        setMessages(prefixMessages);
        setMobileSidebarOpen(false);

        await sendMessageToSession({
          sessionId: branchedSession.id,
          content: userMessage.content,
          baseMessages: prefixMessages,
        });
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "重新生成失败。",
        );
      }
    },
    [branchSession, chatbotId, selectedSessionId, sendMessageToSession, streaming],
  );

  const handleResendUserMessage = useCallback(
    async (message: ChatMessageItem, nextContent: string) => {
      if (!selectedSessionId || streaming) {
        return;
      }

      const trimmed = nextContent.trim();
      if (!trimmed) {
        return;
      }
      setSendError(null);

      try {
        const currentMessages = messagesRef.current;
        const isDraftUser = Boolean(message.localOnly);
        if (isDraftUser) {
          const baseMessages = committedMessages(currentMessages);
          await sendMessageToSession({
            sessionId: selectedSessionId,
            content: trimmed,
            baseMessages,
          });
          return;
        }

        const prefixMessages = committedMessages(currentMessages).filter(
          (item) => item.seq < message.seq,
        );
        const branchedSession = await branchSession(selectedSessionId, message.seq);
        const localSummary = buildSummaryFromMessages(
          branchedSession,
          chatbotId,
          prefixMessages,
          trimmed,
        );

        setSessions((current) => moveSessionToFront(current, localSummary));
        setSelectedSessionId(branchedSession.id);
        setSessionStatus(branchedSession.status);
        setMessages(prefixMessages);
        setMobileSidebarOpen(false);

        await sendMessageToSession({
          sessionId: branchedSession.id,
          content: trimmed,
          baseMessages: prefixMessages,
        });
      } catch (error) {
        setSendError(
          error instanceof Error ? error.message : "重发消息失败。",
        );
      }
    },
    [branchSession, chatbotId, selectedSessionId, sendMessageToSession, streaming],
  );

  const sidebarContent = (
    <div className="flex h-full flex-col overflow-hidden rounded-[30px] border border-[#E7ECF3] bg-white/96 shadow-[0_18px_42px_rgba(31,42,68,0.06)]">
      <div className="border-b border-[#E7ECF3] px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-[18px] font-semibold tracking-tight text-slate-50">
              {bot?.name ?? "聊天机器人"}
            </h2>
            <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-slate-500">
              <span className="shrink-0 whitespace-nowrap">
                {totalSessionCount} 个会话
              </span>
              {sidebarDescription ? (
                <>
                  <span className="shrink-0">·</span>
                  <span className="min-w-0 flex-1 truncate">
                    {sidebarDescription}
                  </span>
                </>
              ) : null}
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileSidebarOpen(false)}
            aria-label="关闭会话列表"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="relative mt-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            value={sessionQuery}
            onChange={(event) => setSessionQuery(event.target.value)}
            placeholder="搜索会话标题或内容"
            className="h-10 rounded-2xl border-[#E7ECF3] bg-[#FCFDFF] pl-9"
          />
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="min-w-0 space-y-5 overflow-x-hidden px-3 pb-4 pt-3 pr-4">
          {groupedSessions.length === 0 ? (
            <div className="rounded-[22px] border border-dashed border-[#E7ECF3] bg-[#FCFDFF] px-4 py-10 text-center">
              <MessageSquare className="mx-auto h-8 w-8 text-slate-500" />
              <p className="mt-3 text-sm text-slate-300">
                {sessionQuery.trim()
                  ? "没有匹配到会话，试试更短的关键词。"
                  : "还没有聊天记录，先开始一轮新的对话吧。"}
              </p>
            </div>
          ) : (
            groupedSessions.map((group) => (
              <section key={group.label} className="space-y-2">
                <div className="px-2 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">
                  {group.label}
                </div>
                <div className="space-y-1.5">
                  {group.items.map((item) => {
                    const isSelected = item.id === selectedSessionId;
                    const isRenaming = item.id === renamingSessionId;
                    const isMenuOpen = item.id === sessionMenuId;
                    const isRenamePending = sessionActionId === `rename-${item.id}`;
                    const isDeletePending = sessionActionId === `delete-${item.id}`;
                    const rowClassName = cn(
                      "min-w-0 w-full rounded-[20px] px-3 py-3 text-left transition-colors",
                      isSelected ? "bg-[#EFF4FF]" : "hover:bg-[#F7F9FD]",
                    );

                    if (isRenaming) {
                      return (
                        <div
                          key={item.id}
                          data-session-menu-root="true"
                          className={cn(rowClassName, "border border-[#E7ECF3] bg-white")}
                        >
                          <Input
                            autoFocus
                            value={renamingValue}
                            onChange={(event) => setRenamingValue(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void submitRenameSession(item.id);
                              }
                              if (event.key === "Escape") {
                                event.preventDefault();
                                cancelRenameSession();
                              }
                            }}
                            onBlur={() => void submitRenameSession(item.id)}
                            placeholder="输入会话标题"
                            disabled={isRenamePending}
                            className="h-9 rounded-xl border-[#DCE4F1] bg-[#FCFDFF] px-3 text-sm"
                          />
                          <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                            <span>Enter 保存，Esc 取消</span>
                            {isRenamePending ? (
                              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                          </div>
                        </div>
                      );
                    }

                    return (
                      <div key={item.id} className="group/session relative min-w-0">
                        <button
                          type="button"
                          onClick={() => void openSession(item.id)}
                          disabled={conversationLoading || streaming || isDeletePending}
                          className={cn(rowClassName, "pr-11")}
                        >
                          <div className="min-w-0 overflow-hidden">
                            <div className="flex min-w-0 items-start justify-between gap-3">
                              <p
                                className={cn(
                                  "min-w-0 flex-1 break-words line-clamp-1 text-sm font-medium",
                                  isSelected ? "text-slate-50" : "text-slate-200",
                                )}
                              >
                                {item.title}
                              </p>
                              <span className="shrink-0 pt-0.5 text-[11px] text-slate-500">
                                {formatSessionTime(item.updated_at)}
                              </span>
                            </div>
                            <p className="mt-1 line-clamp-1 break-all text-[12px] leading-5 text-slate-400">
                              {item.last_message_preview || EMPTY_SESSION_PREVIEW}
                            </p>
                            <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
                              <span
                                className={cn(
                                  "inline-block h-1.5 w-1.5 rounded-full",
                                  sessionStatusDotClass(item.status),
                                )}
                              />
                              <span>{sessionStatusLabel(item.status)}</span>
                              <span>·</span>
                              <span>{item.message_count} 条消息</span>
                            </div>
                          </div>
                        </button>

                        <div
                          data-session-menu-root="true"
                          className="absolute bottom-2.5 right-2"
                        >
                          <button
                            type="button"
                            className={cn(
                              "flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-200",
                              isMenuOpen || isSelected
                                ? "opacity-100"
                                : "pointer-events-none opacity-0 group-hover/session:pointer-events-auto group-hover/session:opacity-100",
                            )}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSessionMenuId((current) =>
                                current === item.id ? null : item.id,
                              );
                            }}
                            aria-label="更多操作"
                            title="更多操作"
                            disabled={conversationLoading || streaming || isDeletePending}
                          >
                            {isDeletePending ? (
                              <LoaderCircle className="h-3 w-3 animate-spin" />
                            ) : (
                              <MoreHorizontal className="h-3 w-3" />
                            )}
                          </button>

                          {isMenuOpen && (
                            <div className="absolute bottom-8 right-0 z-20 w-36 rounded-2xl border border-[#E7ECF3] bg-white p-1.5 shadow-[0_18px_40px_rgba(31,42,68,0.12)]">
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-slate-200 transition hover:bg-[#F6F8FC]"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  beginRenameSession(item);
                                }}
                              >
                                <Pencil className="h-4 w-4" />
                                重命名
                              </button>
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-[#F56C6C] transition hover:bg-[#FFF1F1] hover:text-[#E25555]"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  requestDeleteSession(item);
                                }}
                              >
                                <Trash2 className="h-4 w-4" />
                                删除
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F7FB] px-6">
        <div className="text-center">
          <LoaderCircle className="mx-auto h-8 w-8 animate-spin text-slate-300" />
          <p className="mt-3 text-sm text-slate-500">正在加载聊天工作台…</p>
        </div>
      </div>
    );
  }

  if (pageError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F7FB] px-6">
        <div className="max-w-sm text-center">
          <Bot className="mx-auto h-10 w-10 text-slate-400" />
          <p className="mt-4 text-sm text-slate-300">{pageError}</p>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Button variant="secondary" onClick={() => void initChat()}>
              重试
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-hidden bg-[linear-gradient(180deg,#F9FBFF,#F5F7FB)] p-3 text-slate-100 md:p-4">
      <div className="mx-auto flex h-full max-w-[1700px] gap-3">
        <aside className="hidden w-[320px] min-w-0 shrink-0 overflow-x-hidden md:block">
          {sidebarContent}
        </aside>

        {mobileSidebarOpen && (
          <div className="absolute inset-0 z-30 md:hidden">
            <button
              type="button"
              className="absolute inset-0 bg-[rgba(15,23,42,0.18)] backdrop-blur-[2px]"
              onClick={() => setMobileSidebarOpen(false)}
              aria-label="关闭会话列表遮罩"
            />
            <div className="relative m-3 h-[calc(100%-24px)] w-[86vw] max-w-[320px]">
              {sidebarContent}
            </div>
          </div>
        )}

        <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[32px] border border-[#E7ECF3] bg-white shadow-[0_18px_52px_rgba(31,42,68,0.06)]">
          <header className="border-b border-[#EEF2F7] bg-white px-5 py-3 sm:px-6">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="md:hidden"
                  onClick={() => setMobileSidebarOpen(true)}
                  aria-label="打开会话列表"
                >
                  <Menu className="h-4 w-4" />
                </Button>
                <div className="min-w-0">
                  <div className="truncate text-[18px] font-semibold tracking-tight text-slate-50">
                    {bot?.name ?? "聊天机器人"}
                  </div>
                  {hasConversation ? (
                    <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-slate-500">
                      <span className="min-w-0 truncate">
                        {selectedSession?.title || EMPTY_SESSION_TITLE}
                      </span>
                      <span>·</span>
                      <span
                        className={cn(
                          "inline-block h-1.5 w-1.5 rounded-full",
                          sessionStatusDotClass(sessionStatus),
                        )}
                      />
                      <span>{sessionStatusLabel(sessionStatus)}</span>
                    </div>
                  ) : (
                    <div className="mt-1 text-xs text-slate-500">
                      开始一轮新的对话
                    </div>
                  )}
                </div>
              </div>

              <Button
                type="button"
                variant={hasConversation ? "secondary" : "ghost"}
                size="sm"
                className="h-9 rounded-full border border-[#E7ECF3] bg-white px-3.5 text-slate-100 hover:bg-[#F7F9FD]"
                onClick={() => void startNewChat()}
                disabled={creatingSession || streaming}
              >
                {creatingSession ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                新对话
              </Button>
            </div>
          </header>

          {sendError && (
            <div className="border-b border-rose-300/15 bg-rose-500/8 px-4 py-2 text-center text-xs text-rose-100">
              {sendError}
            </div>
          )}

          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
            {conversationLoading && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-[rgba(245,247,251,0.82)] backdrop-blur-[2px]">
                <div className="rounded-lg border border-[#E7ECF3] bg-white px-3 py-2 text-sm text-slate-300">
                  <span className="inline-flex items-center gap-2">
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    正在切换会话…
                  </span>
                </div>
              </div>
            )}

            <ChatWidget
              messages={messages}
              disabled={
                conversationLoading ||
                !selectedSessionId ||
                sessionStatus !== "active"
              }
              disabledReason={
                !selectedSessionId
                  ? "先在左侧选择一个会话"
                  : conversationLoading
                    ? "正在加载会话内容"
                    : sessionStatus === "completed"
                      ? "当前会话已完成，请开始新对话"
                      : "当前会话已过期，请开始新对话"
              }
              isStreaming={streaming}
              loading={conversationLoading}
              onStopStreaming={handleStopStreaming}
              onRegenerateAssistantMessage={handleRegenerateAssistant}
              onResendUserMessage={handleResendUserMessage}
              onSend={handleSend}
              className={cn("h-full bg-white", conversationLoading && "opacity-75")}
            />
          </div>
        </section>
      </div>

      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除这个会话？</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget
                ? `会话“${deleteTarget.title}”会从列表和聊天记录中移除，这个操作不可撤销。`
                : "删除后将无法恢复。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton
              disabled={Boolean(
                deleteTarget && sessionActionId === `delete-${deleteTarget.id}`,
              )}
            >
              取消
            </AlertDialogCancelButton>
            <Button
              type="button"
              onClick={() => void handleDeleteSession()}
              disabled={Boolean(
                deleteTarget && sessionActionId === `delete-${deleteTarget.id}`,
              )}
              className="border border-transparent bg-[#F56C6C] text-white shadow-none hover:bg-[#E25555]"
            >
              {deleteTarget && sessionActionId === `delete-${deleteTarget.id}` ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              删除会话
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
