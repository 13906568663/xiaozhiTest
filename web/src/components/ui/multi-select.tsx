"use client";

import * as React from "react";
import { Check, ChevronDown, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type MultiSelectOption = {
  value: string;
  label: string;
};

type MultiSelectProps = {
  value: string[];
  onChange?: (value: string[]) => void;
  options: MultiSelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  loading?: boolean;
};

export function MultiSelect({
  value,
  onChange,
  options,
  placeholder = "请选择",
  className,
  disabled,
  loading,
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const containerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q));
  }, [options, search]);

  const toggle = (val: string) => {
    if (value.includes(val)) {
      onChange?.(value.filter((v) => v !== val));
    } else {
      onChange?.([...value, val]);
    }
  };

  const removeTag = (val: string, e: React.MouseEvent) => {
    e.stopPropagation();
    onChange?.(value.filter((v) => v !== val));
  };

  const selectedLabels = React.useMemo(() => {
    const map = new Map(options.map((o) => [o.value, o.label]));
    return value.map((v) => ({ value: v, label: map.get(v) ?? v }));
  }, [value, options]);

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div
        className={cn(
          "flex min-h-9 cursor-pointer flex-wrap items-center gap-1.5 rounded-md border border-[var(--el-border-base)] bg-white px-3 py-1.5 transition-colors",
          open && "border-[var(--el-primary)]",
          disabled && "cursor-not-allowed opacity-50",
        )}
        onClick={() => {
          if (disabled) return;
          setOpen(!open);
          if (!open) setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        {selectedLabels.length === 0 && !open && (
          <span className="text-sm text-[var(--el-text-placeholder)]">{placeholder}</span>
        )}
        {selectedLabels.map((t) => (
          <span
            key={t.value}
            className="inline-flex items-center gap-1 rounded bg-[var(--el-primary-light-9)] px-2 py-0.5 text-[11px] text-[var(--el-primary)]"
          >
            {t.label}
            {!disabled && (
              <button
                type="button"
                className="flex items-center text-[var(--el-primary)] hover:text-[var(--el-primary-active)]"
                onClick={(e) => removeTag(t.value, e)}
              >
                <X className="size-3" />
              </button>
            )}
          </span>
        ))}
        {open && (
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="min-w-[60px] flex-1 border-none bg-transparent text-sm text-[var(--el-text-primary)] outline-none placeholder:text-[var(--el-text-placeholder)]"
            placeholder="搜索…"
            onClick={(e) => e.stopPropagation()}
          />
        )}
        <ChevronDown
          className={cn(
            "ml-auto size-3.5 shrink-0 text-[var(--el-text-placeholder)] transition-transform",
            open && "rotate-180",
          )}
        />
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-[220px] overflow-y-auto rounded-md border border-[var(--el-border-light)] bg-white shadow-lg thin-scrollbar">
          {loading ? (
            <div className="px-3 py-4 text-center text-xs text-[var(--el-text-placeholder)]">
              加载中…
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-[var(--el-text-placeholder)]">
              {options.length === 0 ? "暂无可选项" : "无匹配结果"}
            </div>
          ) : (
            filtered.map((opt) => {
              const selected = value.includes(opt.value);
              return (
                <div
                  key={opt.value}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm transition-colors hover:bg-[var(--el-primary-light-9)]",
                    selected && "text-[var(--el-primary)]",
                  )}
                  onClick={() => toggle(opt.value)}
                >
                  <div
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded border transition-colors",
                      selected
                        ? "border-[var(--el-primary)] bg-[var(--el-primary)]"
                        : "border-[var(--el-border-base)]",
                    )}
                  >
                    {selected && <Check className="size-3 text-white" />}
                  </div>
                  <span className="min-w-0 truncate">{opt.label}</span>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
