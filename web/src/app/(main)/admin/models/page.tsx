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
import { ToggleSwitch } from "@/components/ui/toggle-switch";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type CapabilityRow = {
  id: string;
  type: string;
  code: string;
  name: string;
  description?: string | null;
  status: string;
  config_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

function readConfigString(cfg: Record<string, unknown>, key: string): string {
  const v = cfg[key];
  return typeof v === "string" && v.trim() ? v : "";
}

function firstAvailableModelName(cfg: Record<string, unknown>): string {
  const models = cfg.available_models;
  if (!Array.isArray(models) || models.length === 0) return "";
  const first = models[0] as Record<string, unknown>;
  const name = first?.model_name;
  return typeof name === "string" && name ? name : "";
}

export default function AdminModelsPage() {
  const router = useRouter();
  const [allRows, setAllRows] = useState<CapabilityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [codeDraft, setCodeDraft] = useState("");
  const [codeFilter, setCodeFilter] = useState("");
  const [nameDraft, setNameDraft] = useState("");
  const [nameFilter, setNameFilter] = useState("");

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<CapabilityRow[]>("/capabilities");
      setAllRows(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载失败");
      setAllRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const modelRows = useMemo(() => allRows.filter((r) => r.type === "model"), [allRows]);

  const filtered = useMemo(() => {
    const c = codeFilter.trim().toLowerCase();
    const n = nameFilter.trim().toLowerCase();
    return modelRows.filter((r) => {
      if (c && !r.code.toLowerCase().includes(c)) return false;
      if (n && !r.name.toLowerCase().includes(n)) return false;
      return true;
    });
  }, [modelRows, codeFilter, nameFilter]);

  const total = filtered.length;
  const pageData = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  );

  const handleToggleStatus = useCallback(
    async (row: CapabilityRow, nextActive: boolean) => {
      const nextStatus = nextActive ? "active" : "inactive";
      if (row.status === nextStatus) return;
      setTogglingId(row.id);
      try {
        await apiClient.put(`/capabilities/${row.id}`, {
          type: "model",
          code: row.code,
          name: row.name,
          description: row.description ?? null,
          status: nextStatus,
          config_json: { ...row.config_json },
        });
        await loadList();
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "更新状态失败");
      } finally {
        setTogglingId(null);
      }
    },
    [loadList],
  );

  const handleConfirmDelete = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(`/capabilities/${confirmTarget.id}`);
      await loadList();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  const applySearch = useCallback(() => {
    setCodeFilter(codeDraft);
    setNameFilter(nameDraft);
    setPage(1);
  }, [codeDraft, nameDraft]);

  const filterFields: FilterField[] = useMemo(
    () => [
      {
        key: "code",
        label: "编码",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入编码"
            value={codeDraft}
            onChange={(e) => setCodeDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applySearch();
            }}
          />
        ),
      },
      {
        key: "name",
        label: "名称",
        render: () => (
          <Input
            className="h-8 border-[#DCDCDC]"
            placeholder="请输入名称"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applySearch();
            }}
          />
        ),
      },
    ],
    [codeDraft, nameDraft, applySearch],
  );

  const columns: Column<CapabilityRow>[] = useMemo(
    () => [
      {
        key: "code",
        title: "编码",
        width: 120,
        render: (v, row) => (
          <button
            type="button"
            className="font-medium text-[#409EFF] hover:underline"
            onClick={() => router.push(`/admin/models/${row.id}/edit`)}
          >
            {String(v ?? "")}
          </button>
        ),
      },
      {
        key: "name",
        title: "名称",
        render: (_, row) => row.name,
      },
      {
        key: "provider",
        title: "提供方",
        width: 168,
        render: (_, row) => {
          const cfg = row.config_json || {};
          const m = readConfigString(cfg, "api_model");
          return m || "—";
        },
      },
      {
        key: "api_host",
        title: "API 主机",
        render: (_, row) => {
          const cfg = row.config_json || {};
          const host = readConfigString(cfg, "api_host");
          return host ? (
            <span className="font-mono text-[13px] text-[#909399]">{host}</span>
          ) : (
            "—"
          );
        },
      },
      {
        key: "default_model",
        title: "默认模型",
        width: 132,
        render: (_, row) => {
          const cfg = row.config_json || {};
          const name = firstAvailableModelName(cfg);
          return name || "—";
        },
      },
      {
        key: "status",
        title: "状态",
        width: 76,
        align: "center",
        render: (_, row) => (
          <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
            <ToggleSwitch
              checked={row.status === "active"}
              disabled={togglingId === row.id}
              onChange={(checked) => void handleToggleStatus(row, checked)}
            />
          </div>
        ),
      },
      {
        key: "actions",
        title: "操作",
        width: 140,
        render: (_, row) => (
          <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="rounded border border-[#DCDFE6] px-2.5 py-1 text-[11px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
              onClick={() => router.push(`/admin/models/${row.id}/edit`)}
            >
              编辑
            </button>
            <button
              type="button"
              disabled={deletingId === row.id}
              className="rounded border border-[#FFCDD2] px-2.5 py-1 text-[11px] text-[#F56C6C] transition-colors hover:bg-[#FEF0F0] disabled:opacity-50"
              onClick={() => setConfirmTarget({ id: row.id, name: row.name })}
            >
              删除
            </button>
          </div>
        ),
      },
    ],
    [router, togglingId, deletingId, handleToggleStatus],
  );

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        title="模型管理"
        description="管理 AI 模型供应商连接配置与可用模型目录，每个供应商对应一组 API 凭据和模型列表。"
        breadcrumb={[{ label: "管理中心" }, { label: "模型管理" }]}
      />

      <div
        className={cn(
          "flex flex-col gap-3.5 rounded-md border border-[#EBEEF5] bg-white px-[18px] pb-4 pt-3",
          loading && "opacity-70",
        )}
      >
        <FilterBar
          fields={filterFields}
          onSearch={applySearch}
          onReset={() => {
            setCodeDraft("");
            setCodeFilter("");
            setNameDraft("");
            setNameFilter("");
            setPage(1);
          }}
          extra={
            <Button variant="success" size="sm" onClick={() => router.push("/admin/models/create")}>
              新增供应商
            </Button>
          }
        />
        <DataTable<CapabilityRow>
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
