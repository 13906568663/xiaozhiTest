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
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type RoleRead = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  is_system: boolean;
  user_count?: number;
  permissions: { id: string }[];
  created_at: string;
};

function formatDate(d: string) {
  return new Date(d).toLocaleDateString("zh-CN");
}

function OutlineBtn({
  children,
  danger,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  danger?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center rounded px-3 py-[5px] text-xs transition-colors disabled:opacity-50",
        danger
          ? "border border-[#FFCDD2] text-[var(--el-danger)] hover:bg-[var(--el-danger-light-9)]"
          : "border border-[var(--el-border-base)] text-[var(--el-text-regular)] hover:border-[var(--el-primary)] hover:text-[var(--el-primary)]",
      )}
    >
      {children}
    </button>
  );
}

export default function IamRolesPage() {
  const router = useRouter();
  const [roles, setRoles] = useState<RoleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [nameDraft, setNameDraft] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const loadRoles = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<RoleRead[]>("/roles");
      setRoles(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载角色列表失败");
      setRoles([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRoles();
  }, [loadRoles]);

  const filteredRoles = useMemo(() => {
    const q = nameFilter.trim().toLowerCase();
    if (!q) return roles;
    return roles.filter((r) => r.name.toLowerCase().includes(q));
  }, [roles, nameFilter]);

  const total = filteredRoles.length;
  const pageData = useMemo(
    () => filteredRoles.slice((page - 1) * pageSize, page * pageSize),
    [filteredRoles, page, pageSize],
  );

  const doSearch = () => {
    setNameFilter(nameDraft);
    setPage(1);
  };

  const doReset = () => {
    setNameDraft("");
    setNameFilter("");
    setPage(1);
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/roles/${confirmTarget.id}`);
      await loadRoles();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "name",
        label: "角色名称",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入角色名称"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") doSearch();
            }}
          />
        ),
      },
    ],
    [nameDraft],
  );

  const columns: Column<RoleRead>[] = [
    { key: "name", title: "角色名称", width: 150 },
    {
      key: "description",
      title: "说明",
      ellipsis: true,
      render: (_, r) => r.description ?? "—",
    },
    {
      key: "user_count",
      title: "关联用户数",
      width: 88,
      align: "center",
      render: (_, r) => r.user_count ?? 0,
    },
    {
      key: "created_at",
      title: "创建时间",
      width: 100,
      align: "center",
      render: (_, r) => formatDate(r.created_at),
    },
    {
      key: "actions",
      title: "操作",
      width: 160,
      align: "left",
      fixed: "right", 
      render: (_, r) => (
        <span className="inline-flex items-center gap-1.5">
          <OutlineBtn onClick={() => router.push(`/iam/roles/${r.id}/edit`)}>
            权限配置
          </OutlineBtn>
          <OutlineBtn onClick={() => router.push(`/iam/roles/${r.id}/edit`)}>
            编辑
          </OutlineBtn>
          {!r.is_system && (
            <OutlineBtn
              danger
              disabled={deletingId === r.id}
              onClick={() => setConfirmTarget({ id: r.id, name: r.name })}
            >
              删除
            </OutlineBtn>
          )}
        </span>
      ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="角色管理"
        breadcrumb={[{ label: "用户中心" }, { label: "角色管理" }]}
      />

      <div
        className={cn(
          "flex flex-col gap-3.5 rounded border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3",
          loading && "opacity-70",
        )}
      >
        <FilterBar
          fields={filterFields}
          onSearch={doSearch}
          onReset={doReset}
          extra={
            <Button
              variant="success"
              size="sm"
              onClick={() => router.push("/iam/roles/create")}
            >
              新增
            </Button>
          }
        />
        <DataTable<RoleRead>
          columns={columns}
          data={pageData}
          rowKey="id"
          headerClassName="bg-[#FAFAFA]"
          emptyText={loading ? "加载中…" : "暂无数据"}
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
        message={`确定删除「${confirmTarget?.name}」？此操作不可撤销。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
