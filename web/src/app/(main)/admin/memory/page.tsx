"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ActionButtons } from "@/components/ui/action-buttons";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable, type Column } from "@/components/ui/data-table";
import { FilterBar, type FilterField } from "@/components/ui/filter-bar";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Select, type SelectOption } from "@/components/ui/select";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type MemoryRow = {
  id: string;
  user_id: string;
  username: string | null;
  memory_type: string;
  key: string;
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type MemoryListResponse = {
  items: MemoryRow[];
  total: number;
};

const MEMORY_TYPE_OPTIONS: SelectOption[] = [
  { value: "all", label: "全部" },
  { value: "long_term", label: "长期记忆" },
  { value: "short_term", label: "短期记忆" },
];

function formatDateTime(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

function truncateContent(text: string, max = 80): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function entryCountLabel(row: MemoryRow): string {
  const m = row.metadata_json;
  if (typeof m.entry_count === "number") return String(m.entry_count);
  if (Array.isArray(m.entries)) return String(m.entries.length);
  return "1";
}

export default function AdminMemoryPage() {
  const router = useRouter();
  const [items, setItems] = useState<MemoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [userIdDraft, setUserIdDraft] = useState("");
  const [memoryTypeDraft, setMemoryTypeDraft] = useState("all");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [appliedUserId, setAppliedUserId] = useState("");
  const [appliedMemoryType, setAppliedMemoryType] = useState("all");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [refreshSeq, setRefreshSeq] = useState(0);

  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const params: Record<string, string | number> = {
        skip: (page - 1) * pageSize,
        limit: pageSize,
      };
      if (appliedUserId.trim()) {
        params.user_id = appliedUserId.trim();
      }
      if (appliedMemoryType !== "all") {
        params.memory_type = appliedMemoryType;
      }
      if (appliedKeyword.trim()) {
        params.keyword = appliedKeyword.trim();
      }

      const { data } = await apiClient.get<MemoryListResponse>("/memories", { params });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "加载失败";
      setListError(msg);
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedKeyword, appliedMemoryType, appliedUserId, page, pageSize, refreshSeq]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  const handleSearch = useCallback(() => {
    setAppliedUserId(userIdDraft.trim());
    setAppliedMemoryType(memoryTypeDraft);
    setAppliedKeyword(keywordDraft.trim());
    setPage(1);
    setListError(null);
    setRefreshSeq((s) => s + 1);
  }, [userIdDraft, memoryTypeDraft, keywordDraft]);

  const handleReset = useCallback(() => {
    setUserIdDraft("");
    setMemoryTypeDraft("all");
    setKeywordDraft("");
    setAppliedUserId("");
    setAppliedMemoryType("all");
    setAppliedKeyword("");
    setPage(1);
    setItems([]);
    setTotal(0);
    setListError(null);
    setRefreshSeq((s) => s + 1);
  }, []);

  const requestDeleteRow = useCallback((row: MemoryRow) => {
    setConfirmTarget({ id: row.id, name: row.key || "该条记忆" });
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (!confirmTarget) return;
    const { id } = confirmTarget;
    setConfirmTarget(null);
    setDeletingId(id);
    try {
      await apiClient.delete(`/memories/${id}`);
      if (items.length === 1 && page > 1) setPage((p) => p - 1);
      else await fetchList();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "删除失败";
      setListError(msg);
    } finally {
      setDeletingId(null);
    }
  }, [confirmTarget, fetchList, items.length, page]);

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "user_id",
        label: "用户名",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入用户名"
            value={userIdDraft}
            onChange={(e) => setUserIdDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSearch();
            }}
          />
        ),
      },
      {
        key: "memory_type",
        label: "记忆类型",
        render: () => (
          <Select className="h-8 border-[#DCDCDC]" options={MEMORY_TYPE_OPTIONS} value={memoryTypeDraft} onChange={(e) => setMemoryTypeDraft(e.target.value)} />
        ),
      },
      {
        key: "keyword",
        label: "关键词",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder=""
            value={keywordDraft}
            onChange={(e) => setKeywordDraft(e.target.value)}
          />
        ),
      },
      {
        key: "rule_name",
        label: "规则名称",
        render: () => <Input className="h-8 border-[#DCDCDC]" placeholder="" disabled value="" readOnly />,
      },
    ],
    [keywordDraft, memoryTypeDraft, userIdDraft, handleSearch],
  );

  const columns: Column<MemoryRow>[] = useMemo(
    () => [
      {
        key: "user_id",
        title: "用户",
        width: 100,
        render: (_, record) => (
          <span className="block truncate" title={record.username ?? record.user_id}>
            {record.username ?? record.user_id}
          </span>
        ),
      },
      {
        key: "key",
        title: "记忆类型",
        width: 100,
        render: (_, record) => (
          <span className="block truncate text-[12px]" title={record.key}>
            {record.key}
          </span>
        ),
      },
      {
        key: "content",
        title: "内容摘要",
        render: (_, record) => (
          <span className="block min-w-0 truncate" title={record.content}>
            {truncateContent(record.content)}
          </span>
        ),
      },
      {
        key: "entry_count",
        title: "条目数",
        width: 60,
        align: "center",
        render: (_, record) => entryCountLabel(record),
      },
      {
        key: "updated_at",
        title: "最后更新",
        width: 140,
        align: "center",
        render: (_, record) => formatDateTime(record.updated_at),
      },
      {
        key: "actions",
        title: "操作",
        width: 120,
        render: (_, record) => (
          <ActionButtons
            items={[
              { key: "view", label: "查看", onClick: () => router.push(`/admin/memory/${record.id}`) },
              {
                key: "delete",
                label: deletingId === record.id ? "清理中…" : "清理",
                color: "danger",
                disabled: deletingId === record.id,
                onClick: () => requestDeleteRow(record),
              },
            ]}
          />
        ),
      },
    ],
    [deletingId, requestDeleteRow, router],
  );

  const emptyHint = loading ? "加载中…" : "暂无数据";
  const displayRows = items;

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        className="[&_h1]:text-[24px] [&_h1]:leading-tight"
        title="记忆管理"
        description="管理智能体对话记忆数据，查看和维护上下文信息。"
        breadcrumb={[{ label: "管理中心" }, { label: "记忆管理" }]}
      />

      {listError && (
        <div className="rounded-md border border-[var(--el-danger-light-5)] bg-[var(--el-danger-light-9)] px-3 py-2 text-sm text-[var(--el-danger)]">
          {listError}
        </div>
      )}

      <div className={cn("flex flex-col gap-3.5 rounded-md border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3", loading && "opacity-70")}>
        <FilterBar fields={filterFields} onSearch={handleSearch} onReset={handleReset} />
        <DataTable<MemoryRow>
          columns={columns}
          data={displayRows}
          rowKey="id"
          headerClassName="bg-[#FAFAFA]"
          emptyText={emptyHint}
        />
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          onChange={setPage}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setPage(1);
          }}
        />
      </div>

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认清理"
        message={`确定清理「${confirmTarget?.name}」？此操作不可撤销。`}
        confirmText="清理"
        variant="danger"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
