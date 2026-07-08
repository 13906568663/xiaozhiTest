import { cn } from "@/lib/utils";

type AvatarProps = {
  name?: string;
  src?: string;
  size?: number;
  className?: string;
};

export function Avatar({ name, src, size = 28, className }: AvatarProps) {
  const initials = name?.charAt(0)?.toUpperCase() ?? "?";

  if (src) {
    return (
      <img
        src={src}
        alt={name ?? ""}
        className={cn("shrink-0 rounded-full object-cover", className)}
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-[var(--el-primary)] text-white",
        className,
      )}
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden
    >
      {initials}
    </div>
  );
}
