import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type StatCardProps = {
  title: string;
  value: ReactNode;
  description?: string;
  icon?: ReactNode;
  className?: string;
};

export function StatCard({ title, value, description, icon, className }: StatCardProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border border-[#EBEEF5] bg-white px-5 py-4",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-[#909399]">{title}</span>
        {icon}
      </div>
      <div className="text-[28px] font-bold leading-none tracking-tight text-[#303133]">
        {value}
      </div>
      {description && (
        <span className="text-xs text-[#909399]">{description}</span>
      )}
    </div>
  );
}
