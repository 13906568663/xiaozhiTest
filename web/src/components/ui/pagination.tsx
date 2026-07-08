"use client";

import { useState } from "react";

import { Select } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type PaginationProps = {
  current: number;
  pageSize: number;
  total: number;
  onChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: number[];
  className?: string;
  /** 显示「前往 __ 页」输入框（回车跳转） */
  showPageJump?: boolean;
};

function generatePages(current: number, totalPages: number): (number | "...")[] {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);

  const pages: (number | "...")[] = [1];
  if (current > 3) pages.push("...");

  const start = Math.max(2, current - 1);
  const end = Math.min(totalPages - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);

  if (current < totalPages - 2) pages.push("...");
  if (totalPages > 1) pages.push(totalPages);
  return pages;
}

export function Pagination({
  current,
  pageSize,
  total,
  onChange,
  onPageSizeChange,
  pageSizeOptions = [10, 20, 50],
  className,
  showPageJump = false,
}: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pages = generatePages(current, totalPages);
  const [jumpDraft, setJumpDraft] = useState("");

  const commitJump = () => {
    const n = Number.parseInt(jumpDraft.trim(), 10);
    if (!Number.isFinite(n)) return;
    onChange?.(Math.min(totalPages, Math.max(1, n)));
    setJumpDraft("");
  };

  return (
    <div className={cn("flex items-center justify-between py-5 px-3.5", className)}>
      <span className="text-[13px] font-medium text-[#606266]">
        共 {total} 条
      </span>
      <div className="flex items-center gap-3.5">
        <span className="text-xs text-[#909399]">每页</span>
        <Select
          className="w-auto min-w-[4.5rem] [&_select]:h-[30px]"
          value={String(pageSize)}
          onChange={(e) => onPageSizeChange?.(Number(e.target.value))}
          options={pageSizeOptions.map((s) => ({
            value: String(s),
            label: `${s} 条`,
          }))}
        />

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={current <= 1}
            onClick={() => onChange?.(current - 1)}
            className="flex h-[30px] items-center justify-center rounded-md border border-[#E4E7ED] bg-white px-3.5 text-[13px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-40"
          >
            上一页
          </button>

          {pages.map((p, i) =>
            p === "..." ? (
              <span key={`dots-${i}`} className="px-1 text-xs text-[#909399]">
                ...
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => onChange?.(p)}
                className={cn(
                  "flex h-[30px] min-w-[30px] items-center justify-center rounded-md px-3.5 text-[13px] transition-colors",
                  p === current
                    ? "bg-[#409EFF] font-semibold text-white"
                    : "border border-[#E4E7ED] bg-white text-[#606266] hover:border-[#409EFF] hover:text-[#409EFF]",
                )}
              >
                {p}
              </button>
            ),
          )}

          <button
            type="button"
            disabled={current >= totalPages}
            onClick={() => onChange?.(current + 1)}
            className="flex h-[30px] items-center justify-center rounded-md border border-[#E4E7ED] bg-white px-3.5 text-[13px] text-[#606266] transition-colors hover:border-[#409EFF] hover:text-[#409EFF] disabled:opacity-40"
          >
            下一页
          </button>

          {showPageJump && (
            <>
              <span className="text-xs text-[#606266]">前往</span>
              <input
                type="text"
                inputMode="numeric"
                value={jumpDraft}
                onChange={(e) => setJumpDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitJump();
                }}
                className="h-[30px] w-11 rounded-md border border-[#DCDFE6] px-2 text-center text-[12px] text-[#606266] outline-none focus:border-[#409EFF]"
                aria-label="跳转到页码"
              />
              <span className="text-xs text-[#606266]">页</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
