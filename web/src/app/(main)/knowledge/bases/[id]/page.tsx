"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type Column, DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { FormField } from "@/components/ui/form-field";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/* ─── Types ─── */

type KnowledgeBase = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
  chunk_method: string;
  chunk_size: number;
  chunk_overlap: number;
  document_count: number;
};

type DocumentRow = {
  id: string;
  name: string;
  chunk_count: number;
  created_at: string;
  status: string;
  error_message: string | null;
};

/** 与后端 `ChunkSearchResult` 对齐 */
type ChunkSearchResult = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  chunk_index: number;
  content: string;
  score: number;
};

type KnowledgeSearchResponse = {
  query: string;
  results: ChunkSearchResult[];
  total: number;
};

/* ─── Constants ─── */

const CHUNK_METHOD_LABEL: Record<string, string> = {
  fixed: "固定字数",
  semantic: "语义分块",
};

const STATUS_COLOR: Record<string, string> = {
  ready: "text-[#67C23A]",
  completed: "text-[#67C23A]",
  active: "text-[#67C23A]",
  processing: "text-[#E6A23C]",
  pending: "text-[#E6A23C]",
  failed: "text-[#F56C6C]",
  error: "text-[#F56C6C]",
};

const STATUS_LABEL: Record<string, string> = {
  ready: "就绪",
  completed: "就绪",
  active: "就绪",
  processing: "处理中",
  pending: "处理中",
  failed: "失败",
  error: "失败",
};

function formatDatetime(d: string) {
  const date = new Date(d);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${h}:${min}`;
}

function humanFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ─── Upload Dialog ─── */

function UploadDialog({
  open,
  uploading,
  onClose,
  onUpload,
}: {
  open: boolean;
  uploading: boolean;
  onClose: () => void;
  onUpload: (files: File[]) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) setFiles([]);
  }, [open]);

  const addFiles = (newFiles: FileList | null) => {
    if (!newFiles) return;
    const arr = Array.from(newFiles);
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name + f.size));
      return [...prev, ...arr.filter((f) => !existing.has(f.name + f.size))];
    });
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/15" onClick={onClose} aria-hidden />
      <div
        className="relative z-10 flex w-[520px] flex-col overflow-hidden rounded-lg border border-[#E4E7ED] bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-[#EBEEF5] px-5 py-4">
          <h2 className="text-base font-semibold text-[#303133]">上传文档</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#C0C4CC] hover:text-[#909399]"
          >
            <X className="size-[18px]" />
          </button>
        </div>

        <div className="flex flex-col gap-4 px-5 py-4">
          <div
            className={cn(
              "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 transition-colors",
              dragOver
                ? "border-[#409EFF] bg-[#ECF5FF]"
                : "border-[#DCDFE6] bg-[#FAFAFA]",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              addFiles(e.dataTransfer.files);
            }}
          >
            <Upload className="size-8 text-[#C0C4CC]" />
            <p className="text-sm text-[#606266]">
              拖拽文件至此处，或{" "}
              <button
                type="button"
                className="text-[#409EFF] hover:underline"
                onClick={() => inputRef.current?.click()}
              >
                点击上传
              </button>
            </p>
            <p className="text-[11px] text-[#909399]">
              支持 .txt .md .pdf .docx 等文本文件，单文件不超过 20MB
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".txt,.md,.pdf,.docx,.doc,.csv,.json,.html"
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {files.length > 0 && (
            <div className="flex max-h-[200px] flex-col gap-1.5 overflow-y-auto thin-scrollbar">
              {files.map((f, i) => (
                <div
                  key={`${f.name}-${f.size}`}
                  className="flex items-center justify-between rounded border border-[#EBEEF5] bg-white px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-[#303133]">{f.name}</p>
                    <p className="text-[11px] text-[#909399]">{humanFileSize(f.size)}</p>
                  </div>
                  <button
                    type="button"
                    className="ml-2 shrink-0 text-[#C0C4CC] hover:text-[#F56C6C]"
                    onClick={() => removeFile(i)}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EBEEF5] bg-[#FAFAFA] px-5 py-3">
          <button
            type="button"
            disabled={uploading}
            className="rounded-[5px] border border-[#DCDFE6] bg-white px-4 py-2 text-[13px] text-[#606266] hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
            onClick={onClose}
          >
            取消
          </button>
          <button
            type="button"
            disabled={uploading || files.length === 0}
            className="rounded-[5px] bg-[#409EFF] px-5 py-2 text-[13px] text-white hover:bg-[#66b1ff] disabled:opacity-50"
            onClick={() => onUpload(files)}
          >
            {uploading ? "上传中…" : `上传 (${files.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Manual Input Dialog ─── */

function ManualInputDialog({
  open,
  saving,
  onClose,
  onSave,
}: {
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (title: string, content: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  useEffect(() => {
    if (!open) {
      setTitle("");
      setContent("");
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/15" onClick={onClose} aria-hidden />
      <div
        className="relative z-10 flex w-[600px] flex-col overflow-hidden rounded-lg border border-[#E4E7ED] bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-[#EBEEF5] px-5 py-4">
          <h2 className="text-base font-semibold text-[#303133]">手动输入文档</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#C0C4CC] hover:text-[#909399]"
          >
            <X className="size-[18px]" />
          </button>
        </div>

        <div className="flex flex-col gap-3 px-5 py-4">
          <FormField label="文档标题" required>
            <input
              type="text"
              className="h-[34px] w-full rounded-[5px] border border-[#DCDFE6] bg-white px-3 text-[13px] text-[#303133] outline-none transition-colors placeholder:text-[#C0C4CC] focus:border-[#409EFF]"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="如 FAQ 常见问题"
            />
          </FormField>
          <FormField label="文档内容" required>
            <textarea
              className="min-h-[200px] w-full rounded-[5px] border border-[#DCDFE6] bg-white px-3 py-2 text-[13px] leading-relaxed text-[#303133] outline-none transition-colors placeholder:text-[#C0C4CC] focus:border-[#409EFF]"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="粘贴或输入文档内容…"
            />
          </FormField>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#EBEEF5] bg-[#FAFAFA] px-5 py-3">
          <button
            type="button"
            disabled={saving}
            className="rounded-[5px] border border-[#DCDFE6] bg-white px-4 py-2 text-[13px] text-[#606266] hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
            onClick={onClose}
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving || !title.trim() || !content.trim()}
            className="rounded-[5px] bg-[#409EFF] px-5 py-2 text-[13px] text-white hover:bg-[#66b1ff] disabled:opacity-50"
            onClick={() => onSave(title.trim(), content.trim())}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export default function KnowledgeBaseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const kbId = params.id as string;

  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [loading, setLoading] = useState(true);

  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<ChunkSearchResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rebuildingId, setRebuildingId] = useState<string | null>(null);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualSaving, setManualSaving] = useState(false);

  /* ── Data loading ── */

  const loadKb = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<KnowledgeBase>(`/knowledge-bases/${kbId}`);
      setKb(data);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载知识库详情失败");
    } finally {
      setLoading(false);
    }
  }, [kbId]);

  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    try {
      const { data } = await apiClient.get<Array<DocumentRow & { title?: string }>>(
        `/knowledge-bases/${kbId}/documents`,
      );
      const raw = Array.isArray(data) ? data : [];
      setDocs(
        raw.map((d) => ({
          ...d,
          name: d.name ?? (d as { title?: string }).title ?? "—",
        })),
      );
    } catch {
      setDocs([]);
    } finally {
      setDocsLoading(false);
    }
  }, [kbId]);

  useEffect(() => {
    void loadKb();
    void loadDocs();
  }, [loadKb, loadDocs]);

  /* ── Pagination ── */

  const total = docs.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const pageDocs = useMemo(() => {
    const start = (page - 1) * pageSize;
    return docs.slice(start, start + pageSize);
  }, [docs, page, pageSize]);

  /* ── Search ── */

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (!q) return;
    setSearching(true);
    setHasSearched(true);
    try {
      const { data } = await apiClient.post<KnowledgeSearchResponse>(
        `/knowledge-bases/${kbId}/search`,
        { query: q, top_k: 5 },
      );
      const rows = data?.results;
      const sorted = Array.isArray(rows)
        ? [...rows].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
        : [];
      setSearchResults(sorted);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  /* ── Document actions ── */

  const handleDeleteDoc = async () => {
    if (!confirmTarget) return;
    setDeletingId(confirmTarget.id);
    try {
      await apiClient.delete(
        `/knowledge-bases/${kbId}/documents/${confirmTarget.id}`,
      );
      toast.success("删除成功");
      await loadDocs();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  const handleRebuild = async (doc: DocumentRow) => {
    setRebuildingId(doc.id);
    try {
      await apiClient.post(
        `/knowledge-bases/${kbId}/documents/${doc.id}/reindex`,
        {},
      );
      toast.success("已提交重建任务");
      await loadDocs();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "重建索引失败");
    } finally {
      setRebuildingId(null);
    }
  };

  /* ── Upload ── */

  const handleUpload = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      for (const f of files) {
        const formData = new FormData();
        formData.append("file", f);
        await apiClient.post(`/knowledge-bases/${kbId}/documents/upload`, formData, {
          timeout: 120_000,
        });
      }
      toast.success(`成功上传 ${files.length} 个文档`);
      setUploadOpen(false);
      await loadDocs();
      await loadKb();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  /* ── Manual input ── */

  const handleManualSave = async (title: string, content: string) => {
    setManualSaving(true);
    try {
      await apiClient.post(`/knowledge-bases/${kbId}/documents/text`, {
        title,
        content,
        source_type: "text",
      });
      toast.success("文档创建成功");
      setManualOpen(false);
      await loadDocs();
      await loadKb();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setManualSaving(false);
    }
  };

  /* ── Table columns ── */

  const docColumns: Column<DocumentRow>[] = [
    {
      key: "name",
      title: "文档名称",
      width: 250,
      render: (v) => (
        <span className="font-medium text-[#303133]">{String(v ?? "")}</span>
      ),
    },
    {
      key: "chunk_count",
      title: "分块数量",
      width: 80,
      render: (v) => String(v ?? 0),
    },
    {
      key: "created_at",
      title: "创建时间",
      width: 150,
      render: (v) => (typeof v === "string" ? formatDatetime(v) : "—"),
    },
    {
      key: "status",
      title: "状态",
      width: 80,
      render: (v) => {
        const s = String(v ?? "");
        return (
          <span className={STATUS_COLOR[s] ?? "text-[#909399]"}>
            {STATUS_LABEL[s] ?? s}
          </span>
        );
      },
    },
    {
      key: "error_message",
      title: "错误信息",
      width: 170,
      render: (v) => {
        const msg = typeof v === "string" && v ? v : "-";
        return (
          <span className={msg !== "-" ? "text-[#F56C6C]" : "text-[#909399]"}>
            {msg}
          </span>
        );
      },
    },
    {
      key: "actions",
      title: "操作",
      render: (_, row) => (
        <div className="flex items-center justify-end gap-1.5">
          <button
            type="button"
            disabled={rebuildingId === row.id}
            className="rounded border border-[#DCDFE6] px-2.5 py-1 text-[11px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-50"
            onClick={() => void handleRebuild(row)}
          >
            重建索引
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
  ];

  /* ── Meta line ── */

  const metaLine = kb
    ? [
        kb.embedding_model,
        `${kb.embedding_dimensions} 维`,
        CHUNK_METHOD_LABEL[kb.chunk_method] ?? kb.chunk_method,
        `${kb.document_count ?? docs.length} 篇文档`,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  /* ── Render ── */

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[#909399]">
        加载中…
      </div>
    );
  }

  if (!kb) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-[#909399]">
        <span>知识库不存在</span>
        <Button variant="secondary" size="sm" onClick={() => router.push("/knowledge/bases")}>
          返回列表
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-[18px] bg-white px-7 py-6">
      {/* Back button */}
      <button
        type="button"
        className="flex w-fit items-center gap-1.5 rounded-[5px] border border-[#DCDFE6] bg-white px-2.5 py-1.5 text-xs text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF]"
        onClick={() => router.push("/knowledge/bases")}
      >
        <ArrowLeft className="size-3" />
        返回列表
      </button>

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold tracking-wider text-[#C0C4CC]">
            {kb.code}
          </span>
          <h1 className="text-[22px] font-semibold text-[#303133]">{kb.name}</h1>
          <span className="text-xs text-[#909399]">{metaLine}</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => setManualOpen(true)}>
            手动输入
          </Button>
          <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
            上传文件
          </Button>
        </div>
      </div>

      {/* Search panel */}
      <div className="flex flex-col gap-3 rounded-lg border border-[#EBEEF5] bg-white p-4">
        <div className="flex items-center gap-2">
          <span className="size-3.5 rounded-[3px] bg-[#409EFF]" />
          <span className="text-[13px] font-semibold text-[#303133]">检索测试</span>
        </div>
        <div className="flex items-center gap-2.5">
          <div className="flex flex-1 items-center rounded-[5px] border border-[#DCDFE6] bg-white">
            <input
              type="text"
              className="h-9 flex-1 bg-transparent px-3 text-[13px] text-[#303133] outline-none placeholder:text-[#C0C4CC]"
              placeholder="输入检索文本..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSearch();
              }}
            />
          </div>
          <button
            type="button"
            disabled={searching || !searchQuery.trim()}
            className="rounded-[5px] bg-[#409EFF] px-[18px] py-2 text-[13px] text-white hover:bg-[#66b1ff] disabled:opacity-50"
            onClick={() => void handleSearch()}
          >
            检索
          </button>
        </div>

        {hasSearched && (
          <div className="flex flex-col gap-2">
            {searching ? (
              <p className="py-4 text-center text-xs text-[#909399]">检索中…</p>
            ) : searchResults.length === 0 ? (
              <p className="py-4 text-center text-xs text-[#909399]">无匹配结果</p>
            ) : (
              searchResults.map((r, i) => (
                <div
                  key={r.chunk_id ?? i}
                  className="flex flex-col gap-1.5 rounded-[5px] border border-[#EBEEF5] bg-[#FAFAFA] p-3"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-[#606266]">
                      {r.document_title || kb.name}
                    </span>
                    <span className="text-[11px] text-[#909399]">#{r.chunk_index ?? i}</span>
                    <span className="rounded-[10px] bg-[#F0F9EB] px-2 py-0.5 text-[10px] text-[#67C23A]">
                      {(r.score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed text-[#606266]">{r.content}</p>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Document list */}
      <div className="flex flex-col gap-2.5">
        <h3 className="text-[13px] font-semibold text-[#303133]">文档列表</h3>
        <div
          className={cn(
            "rounded border border-[#EBEEF5]",
            docsLoading && "opacity-70",
          )}
        >
          <DataTable<DocumentRow>
            columns={docColumns}
            data={pageDocs}
            rowKey="id"
            emptyText={docsLoading ? "加载中…" : "暂无文档"}
            headerClassName="bg-[#FAFAFA]"
          />
        </div>
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

      {/* Dialogs */}
      <UploadDialog
        open={uploadOpen}
        uploading={uploading}
        onClose={() => !uploading && setUploadOpen(false)}
        onUpload={(files) => void handleUpload(files)}
      />

      <ManualInputDialog
        open={manualOpen}
        saving={manualSaving}
        onClose={() => !manualSaving && setManualOpen(false)}
        onSave={(t, c) => void handleManualSave(t, c)}
      />

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认删除"
        message={`确定删除文档「${confirmTarget?.name}」？此操作不可撤销。`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleDeleteDoc()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
