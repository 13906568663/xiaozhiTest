"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import type { Column } from "@/components/ui/data-table";
import { DataTable } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { FilterBar } from "@/components/ui/filter-bar";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Select } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

type SessionRow = {
  id: string;
  chatbot_id: string;
  chatbot_name?: string | null;
  status: string;
  message_count: number;
  title?: string | null;
  user?: string | null;
  user_name?: string | null;
  updated_at: string;
};

type MessageItem = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  seq: number;
  created_at: string;
};

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "active", label: "active" },
  { value: "completed", label: "completed" },
  { value: "closed", label: "closed" },
];

function formatUpdatedAt(d: string | null | undefined): string {
  if (!d) return "-";
  return new Date(d).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncateSessionId(id: string): string {
  if (id.length <= 8) return id;
  return `${id.slice(0, 8)}...`;
}

export default function AdminSessionsPage() {
  const [items, setItems] = useState<SessionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [chatbotInput, setChatbotInput] = useState("");
  const [chatbotQuery, setChatbotQuery] = useState("");
  const [statusInput, setStatusInput] = useState("");
  const [statusQuery, setStatusQuery] = useState("");
  const [refreshSeq, setRefreshSeq] = useState(0);
  const [loading, setLoading] = useState(false);

  const [messagesOpen, setMessagesOpen] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesSession, setMessagesSession] = useState<SessionRow | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (chatbotQuery.trim()) params.chatbot_id = chatbotQuery.trim();
      if (statusQuery.trim()) params.status = statusQuery.trim();

      const { data } = await apiClient.get<{ items: SessionRow[]; total: number }>("/admin/sessions", {
        params,
      });
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      if (e instanceof ApiError) toast.error(e.message);
      else toast.error("加载失败");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, chatbotQuery, statusQuery, refreshSeq]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const doSearch = useCallback(() => {
    setPage(1);
    setChatbotQuery(chatbotInput.trim());
    setStatusQuery(statusInput);
    setRefreshSeq((s) => s + 1);
  }, [chatbotInput, statusInput]);

  const doReset = useCallback(() => {
    setChatbotInput("");
    setChatbotQuery("");
    setStatusInput("");
    setStatusQuery("");
    setPage(1);
    setRefreshSeq((s) => s + 1);
  }, []);

  const openMessages = async (row: SessionRow) => {
    setMessagesSession(row);
    setMessagesOpen(true);
    setMessages([]);
    setMessagesLoading(true);
    try {
      const { data } = await apiClient.get<{ items: MessageItem[]; total: number }>(`/admin/sessions/${row.id}/messages`, {
        params: { page: 1, page_size: 200, content_max_length: 2000 },
      });
      setMessages(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      if (e instanceof ApiError) toast.error(e.message);
      else toast.error("加载消息失败");
      setMessagesOpen(false);
      setMessagesSession(null);
    } finally {
      setMessagesLoading(false);
    }
  };

  const columns: Column<SessionRow>[] = [
    {
      key: "id",
      title: "会话 ID",
      width: 160,
    },
    {
      key: "user",
      title: "用户",
      width: 140,
      render: (_, row) => {
        const value = row.user?.trim();
        return (
          <span className="block max-w-[120px] truncate" title={value || ""}>
            {value ? value : "—"}
          </span>
        );
      },
    },
    {
      key: "user_name",
      title: "用户名",
      width: 140,
      render: (_, row) => {
        const value = row.user_name?.trim();
        return (
          <span className="block max-w-[120px] truncate" title={value || ""}>
            {value ? value : "—"}
          </span>
        );
      },
    },
    {
      key: "chatbot_name",
      title: "智能体",
      width: 120,
      render: (_, row) => row.chatbot_name || row.chatbot_id || "-",
    },
    {
      key: "message_count",
      title: "消息数",
      width: 56,
      align: "center",
    },
    {
      key: "updated_at",
      title: "最后活跃",
      width: 96,
      align: "center",
      render: (v) => formatUpdatedAt(v as string | null | undefined),
    },
  ];

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        className="[&_h1]:text-[24px] [&_h1]:leading-tight"
        title="会话管理"
        description="查看和管理用户对话会话记录与状态信息。"
        breadcrumb={[{ label: "管理中心" }, { label: "会话管理" }]}
      />

      <div className={cn("flex flex-col gap-3.5 rounded-md border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3", loading && "opacity-70")}>
        <FilterBar
          fields={[
            {
              key: "chatbot_id",
              label: "智能体",
              render: () => (
                <Input
                  className="h-8 border-[#DCDCDC]"
                  placeholder="智能体 / 机器人 ID"
                  value={chatbotInput}
                  onChange={(e) => setChatbotInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") doSearch();
                  }}
                />
              ),
            },
            {
              key: "status",
              label: "状态",
              render: () => (
                <Select
                  className="h-8 border-[#DCDCDC]"
                  value={statusInput}
                  onChange={(e) => setStatusInput(e.target.value)}
                  options={STATUS_OPTIONS}
                />
              ),
            },
            {
              key: "creator",
              label: "创建人",
              render: () => <Input className="h-8 border-[#DCDCDC]" placeholder="" disabled value="" readOnly />,
            },
            {
              key: "rule_name",
              label: "规则名称",
              render: () => <Input className="h-8 border-[#DCDCDC]" placeholder="" disabled value="" readOnly />,
            },
          ]}
          onSearch={doSearch}
          onReset={doReset}
        />
        <DataTable
          columns={columns}
          data={items}
          rowKey="id"
          headerClassName="bg-[#FAFAFA]"
          emptyText={loading ? "加载中…" : "暂无数据"}
          onRowClick={(row) => void openMessages(row)}
        />
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          onChange={setPage}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPage(1);
          }}
        />
      </div>

      <Dialog
        open={messagesOpen}
        onClose={() => !messagesLoading && setMessagesOpen(false)}
        title={messagesSession ? `会话消息 · ${truncateSessionId(messagesSession.id)}` : "会话消息"}
        description={messagesSession ? `完整 ID：${messagesSession.id}` : undefined}
        width={760}
        footer={
          <Button type="button" variant="secondary" onClick={() => setMessagesOpen(false)} disabled={messagesLoading}>
            关闭
          </Button>
        }
      >
        <div className="h-[520px] overflow-y-auto thin-scrollbar">
          {messagesLoading && <p className="text-sm text-[var(--el-text-secondary)]">加载中…</p>}
          {!messagesLoading && messages.length === 0 && (
            <p className="text-sm text-[var(--el-text-placeholder)]">暂无消息</p>
          )}
          {!messagesLoading && messages.length > 0 && (
            <div className="flex flex-col gap-3">
              {messages.map((m) => {
                const isUser = m.role === "user";
                return (
                  <div
                    key={m.id}
                    className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}
                  >
                    <div
                      className={cn(
                        "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed",
                        isUser
                          ? "rounded-br-md bg-[var(--el-primary)] text-white"
                          : "rounded-bl-md border border-[var(--el-border-lighter)] bg-[var(--el-color-info-bg)]/40 text-[var(--el-text-regular)]",
                      )}
                    >
                      <div className="mb-1 text-[10px] font-medium opacity-80">
                        {m.role}
                        {m.created_at ? ` · ${formatUpdatedAt(m.created_at)}` : ""}
                      </div>
                      <div className="prose prose-sm max-w-none break-words">
                        {m.content ? (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {m.content}
                          </ReactMarkdown>
                        ) : (
                          <span className="italic text-[var(--el-text-placeholder)]">（空消息）</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Dialog>
    </div>
  );
}
