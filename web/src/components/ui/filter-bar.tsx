"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type FilterField = {
  key: string;
  label: string;
  render: () => ReactNode;
};

type FilterBarProps = {
  fields: FilterField[];
  onSearch?: () => void;
  onReset?: () => void;
  extra?: ReactNode;
  className?: string;
};

export function FilterBar({ fields, onSearch, onReset, extra, className }: FilterBarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-end gap-5 rounded border border-[#E5E5E5] bg-white px-3 py-3.5",
        className,
      )}
    >
      {fields.map((field) => (
        <div key={field.key} className="flex min-w-[160px] flex-1 flex-col gap-1.5">
          <span className="text-sm font-semibold text-[var(--el-text-regular)]">{field.label}</span>
          {field.render()}
        </div>
      ))}
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          className="h-8 rounded px-6 text-[13px] font-semibold text-white bg-[#1CA0DC] hover:opacity-90 transition-opacity"
          onClick={onSearch}
        >
          查询
        </button>
        <button
          type="button"
          className="h-8 rounded px-6 text-[13px] font-semibold text-white bg-[#B3B3B3] hover:opacity-90 transition-opacity"
          onClick={onReset}
        >
          重置
        </button>
        {extra}
      </div>
    </div>
  );
}
