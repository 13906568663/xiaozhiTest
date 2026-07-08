import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { FieldError } from "@/components/ui/field-error";

type FormFieldProps = {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  layout?: "vertical" | "horizontal";
  labelWidth?: number;
};

export function FormField({
  label,
  required,
  error,
  hint,
  children,
  className,
  layout = "vertical",
  labelWidth = 80,
}: FormFieldProps) {
  if (layout === "horizontal") {
    return (
      <div className={cn("flex items-start gap-4", className)}>
        <label
          className="shrink-0 pt-2 text-right text-sm text-[var(--el-text-regular)]"
          style={{ width: labelWidth }}
        >
          {required && <span className="mr-0.5 text-[var(--el-danger,#F56C6C)]">*</span>}
          {label}
        </label>
        <div className="min-w-0 flex-1 flex flex-col gap-0.5">
          {children}
          {hint && !error && (
            <span className="text-xs text-[var(--el-text-placeholder)]">{hint}</span>
          )}
          <FieldError message={error} />
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-baseline justify-between">
        <label className="text-sm font-medium text-[var(--el-text-regular)]">
          {label}
          {required && <span className="ml-0.5 text-[var(--el-danger,#F56C6C)]">*</span>}
        </label>
        {hint && !error && (
          <span className="text-xs text-[var(--el-text-placeholder)]">{hint}</span>
        )}
      </div>
      {children}
      <FieldError message={error} />
    </div>
  );
}
