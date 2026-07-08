"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { type Column, DataTable } from "@/components/ui/data-table";
import { FilterBar, type FilterField } from "@/components/ui/filter-bar";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Select, type SelectOption } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type SkillRow = {
  id: string;
  code: string;
  description: string | null;
  status: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

type ListResponse = {
  items: SkillRow[];
  total: number;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${day} ${h}:${min}`;
  } catch {
    return "—";
  }
}

function RowActionBtn({
  children,
  variant = "default",
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  variant?: "default" | "danger";
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded px-3 py-[5px] text-xs transition-colors disabled:opacity-50",
        variant === "danger"
          ? "border border-[#FFCDD2] text-[var(--el-danger)] hover:bg-[var(--el-danger-light-9)]"
          : "border border-[var(--el-border-base)] text-[var(--el-text-regular)] hover:border-[var(--el-text-placeholder)]",
      )}
    >
      {children}
    </button>
  );
}

export default function SkillsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [codeDraft, setCodeDraft] = useState("");
  const [codeFilter, setCodeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("all");
  const [refreshSeq, setRefreshSeq] = useState(0);

  const [items, setItems] = useState<SkillRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; code: string } | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (codeFilter.trim()) params.code = codeFilter.trim();
      if (statusFilter !== "all") params.status = statusFilter;
      const { data } = await apiClient.get<ListResponse>("/skills", { params });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载列表失败");
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, codeFilter, statusFilter, refreshSeq]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/skills/${confirmTarget.id}`);
      toast.success("已删除");
      await loadList();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  const applyFilters = useCallback(() => {
    setCodeFilter(codeDraft.trim());
    setPage(1);
    setRefreshSeq((s) => s + 1);
  }, [codeDraft]);

  const resetFilters = useCallback(() => {
    setCodeDraft("");
    setCodeFilter("");
    setStatusFilter("all");
    setPage(1);
    setRefreshSeq((s) => s + 1);
  }, []);

  const statusFilterOptions: SelectOption[] = useMemo(
    () => [
      { value: "all", label: "全部" },
      { value: "active", label: "启用" },
      { value: "inactive", label: "停用" },
    ],
    [],
  );

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "code",
        label: "技能编码",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="按 SKILL.md 的 name 模糊匹配"
            value={codeDraft}
            onChange={(e) => setCodeDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applyFilters();
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
            value={statusFilter}
            options={statusFilterOptions}
            onChange={(e) => {
              setStatusFilter(e.target.value as "all" | "active" | "inactive");
              setPage(1);
            }}
          />
        ),
      },
    ],
    [codeDraft, statusFilter, statusFilterOptions, applyFilters],
  );

  const columns: Column<SkillRow>[] = useMemo(
    () => [
      {
        key: "code",
        title: "编码 (name)",
        width: 180,
        render: (_, row) => (
          <span className="font-mono text-xs text-[var(--el-text-primary)]">{row.code}</span>
        ),
      },
      {
        key: "description",
        title: "描述",
        render: (_, row) => (
          <span
            className="block max-w-[480px] truncate text-xs text-[var(--el-text-regular)]"
            title={row.description ?? ""}
          >
            {row.description || "—"}
          </span>
        ),
      },
      {
        key: "status",
        title: "状态",
        width: 72,
        align: "center",
        render: (_, row) => {
          const active = row.status === "active";
          return (
            <span className="inline-flex items-center justify-center gap-1.5">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-sm",
                  active ? "bg-[var(--el-success)]" : "bg-[var(--el-info)]",
                )}
              />
              <span
                className={cn(
                  "text-xs font-semibold",
                  active ? "text-[var(--el-success)]" : "text-[var(--el-text-secondary)]",
                )}
              >
                {active ? "启用" : "停用"}
              </span>
            </span>
          );
        },
      },
      {
        key: "created_by",
        title: "创建人",
        width: 110,
        align: "center",
        render: (v) => (
          <span className="text-xs text-[var(--el-text-regular)]">{v ? String(v) : "—"}</span>
        ),
      },
      {
        key: "updated_at",
        title: "更新时间",
        width: 150,
        align: "center",
        render: (v) => (
          <span className="text-[11px] text-[var(--el-text-regular)]">
            {formatDateTime(typeof v === "string" ? v : null)}
          </span>
        ),
      },
      {
        key: "actions",
        title: "操作",
        fixed: "right",
        width: 160,
        render: (_, row) => (
          <div className="flex items-center gap-1.5">
            <RowActionBtn onClick={() => router.push(`/skills/${row.id}/edit`)}>
              编辑
            </RowActionBtn>
            <RowActionBtn
              variant="danger"
              disabled={deletingId === row.id}
              onClick={() => setConfirmTarget({ id: row.id, code: row.code })}
            >
              删除
            </RowActionBtn>
          </div>
        ),
      },
    ],
    [deletingId, router],
  );

  return (
    <div className="flex min-h-full flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="技能管理"
        description="以 SKILL.md（YAML frontmatter + markdown 正文）形式存储的可复用提示词单元。模板节点可挂载技能，运行时其正文将拼接进节点 prompt。"
        breadcrumb={[{ label: "技能中心" }, { label: "技能管理" }]}
      />

      <div
        className={cn(
          "flex flex-col gap-3.5 rounded border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3",
          loading && "opacity-70",
        )}
      >
        <FilterBar
          fields={filterFields}
          onSearch={applyFilters}
          onReset={resetFilters}
          extra={
            <Button
              variant="success"
              size="sm"
              onClick={() => router.push("/skills/create")}
            >
              新增技能
            </Button>
          }
        />
        <DataTable<SkillRow>
          columns={columns}
          data={items}
          rowKey="id"
          emptyText={loading ? "加载中…" : "暂无技能。点击右上角「新增技能」开始。"}
          headerClassName="bg-[#FAFAFA]"
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
        title="确认删除"
        message={`确定删除技能「${confirmTarget?.code}」？此操作不可撤销，已挂载该技能的模板节点会自动跳过它。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
