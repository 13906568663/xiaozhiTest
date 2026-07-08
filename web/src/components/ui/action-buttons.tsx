import { cn } from "@/lib/utils";

export type ActionItem = {
  key: string;
  label: string;
  color?: "primary" | "success" | "danger" | "warning";
  onClick?: () => void;
  disabled?: boolean;
};

const actionColorMap = {
  primary: "text-[var(--el-primary)] hover:text-[var(--el-primary-hover)]",
  success: "text-[var(--el-success)] hover:text-[var(--el-success-hover)]",
  danger: "text-[var(--el-danger)] hover:text-[var(--el-danger-hover)]",
  warning: "text-[var(--el-warning)] hover:text-[var(--el-warning-hover)]",
} as const;

type ActionButtonsProps = {
  items: ActionItem[];
  className?: string;
};

export function ActionButtons({ items, className }: ActionButtonsProps) {
  return (
    <span className={cn("inline-flex items-center gap-0", className)}>
      {items.map((item, i) => (
        <span key={item.key} className="inline-flex items-center">
          {i > 0 && (
            <span className="mx-2 text-[var(--el-border-base)]" aria-hidden>|</span>
          )}
          <button
            type="button"
            disabled={item.disabled}
            onClick={item.onClick}
            className={cn(
              "text-[13px] font-normal transition-colors disabled:opacity-50",
              actionColorMap[item.color ?? "primary"],
            )}
          >
            {item.label}
          </button>
        </span>
      ))}
    </span>
  );
}
