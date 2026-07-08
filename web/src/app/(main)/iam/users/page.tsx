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

type UserRow = {
  id: string;
  username: string;
  display_name: string;
  phone?: string;
  department?: string;
  status: "active" | "disabled";
  is_superuser: boolean;
  roles: { id: string; code: string; name: string }[];
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

export default function IamUsersPage() {
  const router = useRouter();
  const [allUsers, setAllUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [usernameDraft, setUsernameDraft] = useState("");
  const [nameDraft, setNameDraft] = useState("");
  const [usernameFilter, setUsernameFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<UserRow[]>("/users");
      setAllUsers(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载用户列表失败");
      setAllUsers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const filteredUsers = useMemo(() => {
    let list = allUsers;
    const uq = usernameFilter.trim().toLowerCase();
    if (uq) list = list.filter((u) => u.username.toLowerCase().includes(uq));
    const nq = nameFilter.trim().toLowerCase();
    if (nq) list = list.filter((u) => (u.display_name ?? "").toLowerCase().includes(nq));
    return list;
  }, [allUsers, usernameFilter, nameFilter]);

  const total = filteredUsers.length;
  const pageData = useMemo(
    () => filteredUsers.slice((page - 1) * pageSize, page * pageSize),
    [filteredUsers, page, pageSize],
  );

  const doSearch = () => {
    setUsernameFilter(usernameDraft);
    setNameFilter(nameDraft);
    setPage(1);
  };

  const doReset = () => {
    setUsernameDraft("");
    setNameDraft("");
    setUsernameFilter("");
    setNameFilter("");
    setPage(1);
  };

  const handleToggleStatus = async (user: UserRow) => {
    try {
      await apiClient.put(`/users/${user.id}`, {
        status: user.status === "active" ? "disabled" : "active",
      });
      await loadList();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "操作失败");
    }
  };

  const handleResetPassword = async (user: UserRow) => {
    try {
      await apiClient.post(`/users/${user.id}/reset-password`, {});
      toast.success("密码已重置");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "重置密码失败");
    }
  };

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/users/${confirmTarget.id}`);
      await loadList();
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
        key: "username",
        label: "用户名",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入用户名"
            value={usernameDraft}
            onChange={(e) => setUsernameDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") doSearch();
            }}
          />
        ),
      },
      {
        key: "name",
        label: "姓名",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入姓名"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") doSearch();
            }}
          />
        ),
      },
    ],
    [usernameDraft, nameDraft],
  );

  const columns: Column<UserRow>[] = [
    { key: "username", title: "用户名", width: 150 },
    {
      key: "display_name",
      title: "姓名",
      width: 120,
      align: "center",
      render: (v) => String(v ?? ""),
    },
    {
      key: "phone",
      title: "手机",
      width: 200,
      align: "center",
      render: (v) => String(v ?? "—"),
    },
    {
      key: "roles",
      title: "角色",
      width: 120,
      render: (_, row) => {
        const names = (row.roles ?? []).map((r) => r.name).filter(Boolean);
        return names.length > 0 ? names.join(" / ") : "—";
      },
    },
    {
      key: "department",
      title: "部门",
      width: 120,
      align: "center",
      render: (v) => String(v ?? "—"),
    },
    {
      key: "status",
      title: "状态",
      width: 52,
      align: "center",
      render: (_, row) => (row.status === "active" ? "正常" : "禁用"),
    },
    {
      key: "created_at",
      title: "创建时间",
      align: "center",
      render: (v) => (typeof v === "string" ? formatDate(v) : "—"),
    },
    {
      key: "actions",
      title: "操作",
      width: 220,
      align: "left",
      render: (_, row) => (
        <span className="inline-flex items-center gap-1.5">
          <OutlineBtn onClick={() => router.push(`/iam/users/${row.id}/edit`)}>
            编辑
          </OutlineBtn>
          <OutlineBtn onClick={() => void handleResetPassword(row)}>
            重置密码
          </OutlineBtn>
          <OutlineBtn onClick={() => void handleToggleStatus(row)}>
            {row.status === "active" ? "禁用" : "启用"}
          </OutlineBtn>
        </span>
      ),
    },
  ];

  return (
    <div className="flex min-h-full flex-col gap-3.5 bg-white px-7 py-6">
      <PageHeader
        title="用户管理"
        breadcrumb={[{ label: "用户中心" }, { label: "用户管理" }]}
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
              onClick={() => router.push("/iam/users/create")}
            >
              新增
            </Button>
          }
        />
        <DataTable<UserRow>
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
