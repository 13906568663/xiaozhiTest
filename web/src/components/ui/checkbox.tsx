import * as React from "react";
import { cn } from "@/lib/utils";

export type CheckboxProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
  indeterminate?: boolean;
  label?: React.ReactNode;
};

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, indeterminate, label, id, ...props }, ref) => {
    const innerRef = React.useRef<HTMLInputElement>(null);
    const resolvedRef = (ref ?? innerRef) as React.RefObject<HTMLInputElement>;

    React.useEffect(() => {
      if (resolvedRef.current) {
        resolvedRef.current.indeterminate = indeterminate ?? false;
      }
    }, [indeterminate, resolvedRef]);

    const input = (
      <input
        type="checkbox"
        id={id}
        ref={resolvedRef}
        className={cn(
          "size-4 shrink-0 cursor-pointer accent-[var(--el-primary)] disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );

    if (label) {
      return (
        <label
          htmlFor={id}
          className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-[var(--el-text-regular)] [&:has(input:disabled)]:cursor-not-allowed [&:has(input:disabled)]:opacity-50"
        >
          {input}
          {label}
        </label>
      );
    }

    return input;
  },
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
