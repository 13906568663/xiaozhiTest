"use client";

import * as React from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

type TagInputProps = {
  value: string[];
  onChange?: (value: string[]) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
};

export function TagInput({ value, onChange, placeholder = "输入后回车添加", className, disabled }: TagInputProps) {
  const [input, setInput] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      if (!value.includes(input.trim())) {
        onChange?.([...value, input.trim()]);
      }
      setInput("");
    } else if (e.key === "Backspace" && !input && value.length > 0) {
      onChange?.(value.slice(0, -1));
    }
  };

  const removeTag = (tag: string) => {
    onChange?.(value.filter((v) => v !== tag));
  };

  return (
    <div
      className={cn(
        "flex min-h-9 flex-wrap items-center gap-2 rounded-md border border-[var(--el-border-base)] bg-white px-3 py-1.5 transition-colors focus-within:border-[var(--el-primary)]",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {value.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded bg-[var(--el-primary-light-9)] px-2 py-0.5 text-[11px] text-[var(--el-primary)]"
        >
          {tag}
          {!disabled && (
            <button
              type="button"
              className="flex items-center text-[var(--el-primary)] hover:text-[var(--el-primary-active)]"
              onClick={(e) => {
                e.stopPropagation();
                removeTag(tag);
              }}
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={value.length === 0 ? placeholder : ""}
        disabled={disabled}
        className="min-w-[60px] flex-1 border-none bg-transparent text-sm text-[var(--el-text-primary)] outline-none placeholder:text-[var(--el-text-placeholder)]"
      />
    </div>
  );
}
