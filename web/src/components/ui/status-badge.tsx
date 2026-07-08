import { cn } from "@/lib/utils";

const colorMap = {
  success: { dot: "bg-[var(--el-success)]", text: "text-[var(--el-success)]" },
  warning: { dot: "bg-[var(--el-warning)]", text: "text-[var(--el-warning)]" },
  danger: { dot: "bg-[var(--el-danger)]", text: "text-[var(--el-danger)]" },
  info: { dot: "bg-[var(--el-info)]", text: "text-[var(--el-info)]" },
  primary: { dot: "bg-[var(--el-primary)]", text: "text-[var(--el-primary)]" },
} as const;

type StatusBadgeProps = {
  status: keyof typeof colorMap;
  label: string;
  className?: string;
};

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const colors = colorMap[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[13px]", colors.text, className)}>
      <span className={cn("size-1.5 shrink-0 rounded-full", colors.dot)} aria-hidden />
      {label}
    </span>
  );
}
