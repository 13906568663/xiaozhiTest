import { cn } from "@/lib/utils";

type FieldErrorProps = {
  message?: string;
  className?: string;
};

/**
 * 固定占位高度的表单字段错误提示。
 * 无论是否有错误都渲染一行，避免错误出现/消失时挤压页面布局。
 */
export function FieldError({ message, className }: FieldErrorProps) {
  const text = message?.trim();
  return (
    <p
      className={cn(
        "mt-0.5 min-h-[14px] text-[10px] leading-[14px]",
        text ? "text-[var(--el-danger,#F56C6C)]" : "text-transparent select-none",
        className,
      )}
      aria-live="polite"
    >
      {text || "\u00a0"}
    </p>
  );
}
