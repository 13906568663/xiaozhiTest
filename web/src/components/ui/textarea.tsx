import * as React from "react";

import { cn } from "@/lib/utils";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          "flex min-h-[80px] w-full rounded border border-[var(--el-border-base)] bg-[var(--el-fill-blank)] px-3 py-1.5 text-sm text-[var(--el-text-primary)] outline-none transition-[box-shadow,border-color] placeholder:text-[var(--el-text-placeholder)] focus-visible:border-[var(--el-primary)] focus-visible:ring-2 focus-visible:ring-[var(--el-primary)]/25 disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
Textarea.displayName = "Textarea";

export { Textarea };
