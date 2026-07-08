"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { type Column, DataTable } from "@/components/ui/data-table";
import { FilterBar, type FilterField } from "@/components/ui/filter-bar";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type PermissionRead = {
  id: string;
  code: string;
  resource: string;
  action: string;
  description: string | null;
  created_at: string;
};

export default function IamPermissionsPage() {
  const router = useRouter();
  const [items, setItems] = useState<PermissionRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchDraft, setSearchDraft] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [confirmTarget, setConfirmTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<PermissionRead[]>("/permissions");
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载权限列表失败");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = searchFilter.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (p) =>
        p.resource.toLowerCase().includes(q) ||
        p.code.toLowerCase().includes(q),
    );
  }, [items, searchFilter]);

  const total = filtered.length;
  const pageData = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  );

  const doSearch = () => {
    setSearchFilter(searchDraft);
    setPage(1);
  };

  const doReset = () => {
    setSearchDraft("");
    setSearchFilter("");
    setPage(1);
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    try {
      await apiClient.delete(`/permissions/${confirmTarget.id}`);
      await load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setConfirmTarget(null);
    }
  };

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "resource",
        label: "菜单权限",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入菜单权限"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") doSearch();
            }}
          />
        ),
      },
    ],
    [searchDraft],
  );

  const columns: Column<PermissionRead>[] = [
    {
      key: "index",
      title: "序号",
      width: 50,
      align: "center",
      render: (_v, _r, idx) => (page - 1) * pageSize + idx + 1,
    },
    {
      key: "resource",
      title: "菜单权限",
      width: 140,
      align: "center",
    },
    {
      key: "actions_desc",
      title: "操作权限",
      render: (_, r) => r.description || r.action || "—",
    },
    {
      key: "actions",
      title: "操作",
      width: 140,
      align: "center",
      render: (_, r) => (
        <span className="inline-flex items-center gap-4">
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[13px] text-[var(--el-primary)] transition-colors hover:opacity-80"
            onClick={() => router.push(`/iam/permissions/${r.id}/edit`)}
          >
            <Pencil className="size-3.5" />
            编辑
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[13px] text-[var(--el-danger)] transition-colors hover:opacity-80"
            onClick={() =>
              setConfirmTarget({ id: r.id, name: r.resource })
            }
          >
            <Trash2 className="size-3.5" />
            删除
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col gap-4 bg-white px-7 py-6">
      <PageHeader
        title="权限管理"
        description="权限管理提供了菜单级权限和按钮级权限的管理功能。"
        breadcrumb={[{ label: "用户中心" }, { label: "权限管理" }]}
      />

      <FilterBar
        fields={filterFields}
        onSearch={doSearch}
        onReset={doReset}
        extra={
          <Button
            variant="success"
            size="sm"
            onClick={() => router.push("/iam/permissions/create")}
          >
            新增
          </Button>
        }
      />

      <div
        className={cn(
          "overflow-hidden rounded border border-t border-[#EBEEF5] bg-white",
          loading && "opacity-70",
        )}
      >
        <DataTable<PermissionRead>
          columns={columns}
          data={pageData}
          rowKey="id"
          headerClassName="bg-[#FAFAFA]"
          emptyText={loading ? "加载中…" : "暂无数据"}
        />
      </div>

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

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认删除"
        message={`确定删除「${confirmTarget?.name}」？此操作不可撤销。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
