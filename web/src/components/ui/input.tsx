import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        "flex h-9 w-full rounded border border-[var(--el-border-base)] bg-[var(--el-fill-blank)] px-3 py-1.5 text-sm text-[var(--el-text-primary)] outline-none transition-[box-shadow,border-color] placeholder:text-[var(--el-text-placeholder)] focus-visible:border-[var(--el-primary)] focus-visible:ring-2 focus-visible:ring-[var(--el-primary)]/25 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
