"use client";

import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

type SearchInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
  onSearch?: (value: string) => void;
};

export function SearchInput({ className, onSearch, ...props }: SearchInputProps) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--el-text-placeholder)]" />
      <input
        type="text"
        className="h-8 w-full rounded border border-[var(--el-border-base)] bg-[var(--el-fill-blank)] pl-9 pr-3 text-sm text-[var(--el-text-primary)] outline-none transition-colors placeholder:text-[var(--el-text-placeholder)] focus:border-[var(--el-primary)]"
        onKeyDown={(e) => {
          if (e.key === "Enter") onSearch?.(e.currentTarget.value);
        }}
        {...props}
      />
    </div>
  );
}
