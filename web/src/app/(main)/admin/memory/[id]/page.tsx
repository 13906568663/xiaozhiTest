"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { cn } from "@/lib/utils";

type MemoryDetail = {
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

type EntryRow = { seq: number; source: string; body: string; created_at: string };

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

function memoryTypeLabel(type: string): string {
  if (type === "long_term") return "长期记忆";
  if (type === "short_term") return "短期记忆";
  return type;
}

function buildEntryRows(detail: MemoryDetail | null): EntryRow[] {
  if (!detail) return [];
  const raw = detail.metadata_json?.entries;
  if (Array.isArray(raw) && raw.length > 0) {
    return raw.map((e: unknown, i: number) => {
      if (e && typeof e === "object") {
        const o = e as Record<string, unknown>;
        return {
          seq: i + 1,
          source: String(o.source ?? o.from ?? "—"),
          body: String(o.content ?? o.body ?? o.text ?? "—"),
          created_at: String(o.created_at ?? o.at ?? ""),
        };
      }
      return { seq: i + 1, source: "—", body: String(e), created_at: "" };
    });
  }
  const lines = detail.content.split(/\n+/).filter(Boolean);
  if (lines.length > 1) {
    return lines.slice(0, 20).map((line, i) => ({
      seq: i + 1,
      source: "对话推断",
      body: line.trim(),
      created_at: "",
    }));
  }
  return [{ seq: 1, source: "存储", body: detail.content, created_at: detail.created_at }];
}

export default function AdminMemoryDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = typeof params.id === "string" ? params.id : "";

  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const { data } = await apiClient.get<MemoryDetail>(`/memories/${id}`);
      setDetail(data);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "加载失败";
      setError(msg);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const allEntries = useMemo(() => buildEntryRows(detail), [detail]);
  const entrySlice = useMemo(() => {
    const start = (page - 1) * pageSize;
    return allEntries.slice(start, start + pageSize);
  }, [allEntries, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [id]);

  if (!id) {
    return (
      <div className="px-7 py-6">
        <p className="text-sm text-[var(--el-text-secondary)]">无效的记忆 ID</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-5 bg-white px-7 py-6">
      <PageHeader
        className="[&_h1]:text-[24px] [&_h1]:leading-tight"
        title="记忆详情"
        breadcrumb={[{ label: "管理中心" }, { label: "记忆管理", href: "/admin/memory" }, { label: "记忆详情" }]}
      />

      <button
        type="button"
        onClick={() => router.push("/admin/memory")}
        className="inline-flex w-fit items-center gap-2 text-[13px] text-[var(--el-primary)] hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        返回列表
      </button>

      {loading && <p className="text-sm text-[var(--el-text-secondary)]">加载中…</p>}
      {error && !loading && <p className="text-sm text-[var(--el-danger)]">{error}</p>}

      {detail && !loading && (
        <div className="flex flex-col gap-5">
          <section className="rounded border border-[#EBEEF5] bg-white p-5 sm:p-6">
            <h2 className="text-base font-semibold text-[var(--el-text-primary)]">基本信息</h2>
            <div className="my-4 h-px w-full bg-[#EBEEF5]" />
            <div className="grid gap-8 sm:grid-cols-2">
              <dl className="flex flex-col gap-5">
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">用户名</dt>
                  <dd className="text-[13px] font-medium text-[var(--el-text-primary)]">{detail.username ?? detail.user_id}</dd>
                </div>
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">记忆类型</dt>
                  <dd className="text-[13px] font-medium text-[var(--el-text-primary)]">{memoryTypeLabel(detail.memory_type)} · {detail.key}</dd>
                </div>
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">创建时间</dt>
                  <dd className="text-[13px] font-medium text-[var(--el-text-primary)]">{formatDateTime(detail.created_at)}</dd>
                </div>
              </dl>
              <dl className="flex flex-col gap-5">
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">条目数</dt>
                  <dd className="text-[13px] font-medium text-[var(--el-text-primary)]">{String(allEntries.length)}</dd>
                </div>
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">最后更新</dt>
                  <dd className="text-[13px] font-medium text-[var(--el-text-primary)]">{formatDateTime(detail.updated_at)}</dd>
                </div>
                <div className="flex gap-3">
                  <dt className="w-20 shrink-0 text-[13px] text-[var(--el-text-secondary)]">状态</dt>
                  <dd className="text-[13px] font-medium text-[#67C23A]">正常</dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="rounded border border-[#EBEEF5] bg-white p-5 sm:p-6">
            <h2 className="text-base font-semibold text-[var(--el-text-primary)]">记忆条目</h2>
            <div className="my-4 h-px w-full bg-[#EBEEF5]" />
            <div className="overflow-x-auto rounded border border-[#EBEEF5]">
              <div className="flex min-w-[640px] border-b border-[#EBEEF5] bg-[#FAFAFA] px-3.5 py-2.5 text-[11px] font-semibold tracking-wide text-[#909399]">
                <div className="w-12 shrink-0">序号</div>
                <div className="w-20 shrink-0">来源</div>
                <div className="min-w-0 flex-1">记忆内容</div>
                <div className="w-[130px] shrink-0 text-center">创建时间</div>
              </div>
              {entrySlice.map((row) => (
                <div
                  key={row.seq}
                  className={cn(
                    "flex min-w-[640px] items-start border-b border-[#EBEEF5] px-3.5 py-3 text-[12px] text-[#606266] last:border-b-0",
                  )}
                >
                  <div className="w-12 shrink-0">{row.seq}</div>
                  <div className="w-20 shrink-0 truncate" title={row.source}>
                    {row.source}
                  </div>
                  <div className="min-w-0 flex-1 pr-2 break-words">{row.body}</div>
                  <div className="w-[130px] shrink-0 text-center whitespace-nowrap">
                    {row.created_at ? formatDateTime(row.created_at) : formatDateTime(detail.updated_at)}
                  </div>
                </div>
              ))}
            </div>
            {allEntries.length > pageSize && (
              <Pagination
                className="border-t border-[#EBEEF5]"
                current={page}
                pageSize={pageSize}
                total={allEntries.length}
                onChange={setPage}
                onPageSizeChange={(s) => {
                  setPageSize(s);
                  setPage(1);
                }}
              />
            )}
          </section>

          <p className="text-xs text-[var(--el-text-placeholder)]">
            原始记录 ID：<span className="font-mono">{detail.id}</span> ·{" "}
            <Link href="/admin/memory" className="text-[var(--el-primary)] hover:underline">
              返回列表
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
