type RoutePlaceholderProps = {
  title: string;
  description?: string;
  breadcrumb?: { label: string; current?: boolean }[];
};

export function RoutePlaceholder({ title, description, breadcrumb }: RoutePlaceholderProps) {
  return (
    <div className="p-5">
      {breadcrumb && breadcrumb.length > 0 && (
        <nav className="mb-4 flex flex-wrap items-center gap-2 text-xs text-[var(--el-text-secondary)]">
          {breadcrumb.map((crumb, i) => (
            <span key={`${crumb.label}-${i}`} className="flex items-center gap-2">
              {i > 0 && (
                <span className="text-[var(--el-text-placeholder)]" aria-hidden>
                  ›
                </span>
              )}
              <span
                className={
                  crumb.current
                    ? "font-semibold text-[var(--el-text-regular)]"
                    : undefined
                }
              >
                {crumb.label}
              </span>
            </span>
          ))}
        </nav>
      )}
      <h1 className="text-xl font-semibold text-[var(--el-text-primary)]">{title}</h1>
      {description && (
        <p className="mt-2 text-sm text-[var(--el-text-secondary)]">{description}</p>
      )}
    </div>
  );
}
