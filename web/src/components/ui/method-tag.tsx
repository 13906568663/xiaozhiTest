import { cn } from "@/lib/utils";

const methodColors: Record<string, string> = {
  GET: "bg-[var(--el-primary-light-9)] text-[var(--el-primary)]",
  POST: "bg-[var(--el-success-light-9)] text-[var(--el-success)]",
  PUT: "bg-[var(--el-warning-light-9)] text-[var(--el-warning)]",
  PATCH: "bg-[var(--el-warning-light-9)] text-[var(--el-warning)]",
  DELETE: "bg-[var(--el-danger-light-9)] text-[var(--el-danger)]",
};

type MethodTagProps = {
  method: string;
  className?: string;
};

export function MethodTag({ method, className }: MethodTagProps) {
  const upper = method.toUpperCase();
  const color = methodColors[upper] ?? "bg-[var(--el-info-light-9)] text-[var(--el-info)]";
  return (
    <span
      className={cn(
        "inline-block rounded px-2 py-0.5 text-xs font-semibold",
        color,
        className,
      )}
    >
      {upper}
    </span>
  );
}
