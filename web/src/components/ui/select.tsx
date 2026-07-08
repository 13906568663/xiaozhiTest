import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "children"> & {
  options: SelectOption[];
  placeholder?: string;
};

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, options, placeholder, ...props }, ref) => {
    return (
      <div className={cn("relative h-9 rounded border border-[var(--el-border-base)] bg-[var(--el-fill-blank)] transition-colors focus-within:border-[var(--el-primary)]", className)}>
        <select
          ref={ref}
          className="block h-full w-full appearance-none border-0 bg-transparent px-3 py-0 pr-8 text-sm text-[var(--el-text-primary)] outline-none disabled:cursor-not-allowed disabled:opacity-50"
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} disabled={opt.disabled}>
              {opt.label}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[var(--el-text-placeholder)]" />
      </div>
    );
  },
);
Select.displayName = "Select";

export { Select };
