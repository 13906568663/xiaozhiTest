"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { OverflowTooltip } from "./tooltip";

export type Column<T> = {
  key: string;
  title: string;
  width?: number | string;
  /** Minimum width when resizing. Defaults to 50. */
  minWidth?: number;
  align?: "left" | "center" | "right";
  fixed?: "left" | "right";
  /** When true, content that overflows the cell width shows a tooltip. Defaults to true for columns without a custom render. */
  ellipsis?: boolean;
  /** Whether this column can be resized by dragging. Defaults to the table-level `resizable`. */
  resizable?: boolean;
  render?: (value: unknown, record: T, index: number) => ReactNode;
};

type DataTableProps<T> = {
  columns: Column<T>[];
  data: T[];
  rowKey: keyof T | ((record: T) => string);
  className?: string;
  headerClassName?: string;
  emptyText?: string;
  /** Enable column resize by dragging header borders. Defaults to true. */
  resizable?: boolean;
  onRowClick?: (record: T) => void;
};

function getRowKey<T>(record: T, rowKey: keyof T | ((record: T) => string)): string {
  if (typeof rowKey === "function") return rowKey(record);
  return String(record[rowKey]);
}

function getCellValue<T>(record: T, key: string): unknown {
  return (record as Record<string, unknown>)[key];
}

const alignClass = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
} as const;

type StickyInfo = {
  side: "left" | "right";
  offset: number;
  isEdge: boolean;
};

const DEFAULT_MIN_WIDTH = 50;

export function DataTable<T>({
  columns,
  data,
  rowKey,
  className,
  headerClassName,
  emptyText = "暂无数据",
  resizable = true,
  onRowClick,
}: DataTableProps<T>) {
  const tableRef = useRef<HTMLTableElement>(null);

  /* ── column widths (runtime, px) ── */
  const [colWidths, setColWidths] = useState<Record<string, number>>({});

  const initWidths = useCallback(() => {
    const table = tableRef.current;
    if (!table) return;
    const ths = table.querySelectorAll<HTMLTableCellElement>("thead th");
    const next: Record<string, number> = {};
    ths.forEach((th, i) => {
      const col = columns[i];
      if (col) next[col.key] = th.getBoundingClientRect().width;
    });
    setColWidths(next);
  }, [columns]);

  useEffect(() => {
    initWidths();
  }, [initWidths]);

  /* ── resize drag state ── */
  const dragging = useRef<{
    colKey: string;
    startX: number;
    startW: number;
    minW: number;
  } | null>(null);

  const onResizeStart = useCallback(
    (e: React.MouseEvent, colKey: string, minW: number) => {
      e.preventDefault();
      e.stopPropagation();
      const startW = colWidths[colKey] ?? 100;
      dragging.current = { colKey, startX: e.clientX, startW, minW };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [colWidths],
  );

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      const d = dragging.current;
      if (!d) return;
      const delta = e.clientX - d.startX;
      const newW = Math.max(d.minW, d.startW + delta);
      setColWidths((prev) => ({ ...prev, [d.colKey]: newW }));
    };
    const onMouseUp = () => {
      if (!dragging.current) return;
      dragging.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  /* ── sticky offsets ── */
  const stickyMap = useMemo(() => {
    const map = new Map<string, StickyInfo>();

    let leftOffset = 0;
    const leftCols = columns.filter((c) => c.fixed === "left");
    leftCols.forEach((col, i) => {
      map.set(col.key, {
        side: "left",
        offset: leftOffset,
        isEdge: i === leftCols.length - 1,
      });
      const w = colWidths[col.key] ?? (typeof col.width === "number" ? col.width : 0);
      leftOffset += w;
    });

    let rightOffset = 0;
    const rightCols = columns.filter((c) => c.fixed === "right");
    for (let i = rightCols.length - 1; i >= 0; i--) {
      const rc = rightCols[i];
      map.set(rc.key, {
        side: "right",
        offset: rightOffset,
        isEdge: i === 0,
      });
      const w = colWidths[rc.key] ?? (typeof rc.width === "number" ? rc.width : 0);
      rightOffset += w;
    }

    return map;
  }, [columns, colWidths]);

  const cellStyle = (col: Column<T>): React.CSSProperties | undefined => {
    const sticky = stickyMap.get(col.key);
    const w = colWidths[col.key];
    if (!w && !col.width && !sticky) return undefined;

    const s: React.CSSProperties = {};
    const effectiveW = w ?? col.width;
    if (effectiveW) {
      s.width = effectiveW;
      s.minWidth = effectiveW;
      s.maxWidth = effectiveW;
    }
    if (sticky) {
      s.position = "sticky";
      s[sticky.side] = sticky.offset;
      if (sticky.isEdge) {
        s.boxShadow =
          sticky.side === "left"
            ? "2px 0 4px -2px rgba(0,0,0,0.06)"
            : "-2px 0 4px -2px rgba(0,0,0,0.06)";
      }
    }
    return s;
  };

  const stickyClass = (col: Column<T>, isHeader: boolean): string => {
    const sticky = stickyMap.get(col.key);
    if (!sticky) return "";
    return isHeader
      ? "z-20 bg-inherit"
      : "z-10 bg-white group-hover/row:bg-[#F5F7FA]";
  };

  return (
    <div className={cn("overflow-x-auto thin-scrollbar", className)}>
      <table ref={tableRef} className="w-max min-w-full border-collapse text-sm">
        <thead>
          <tr className={cn("border-b border-[#EBEEF5]", headerClassName)}>
            {columns.map((col) => {
              const colResizable = col.resizable ?? resizable;
              return (
                <th
                  key={col.key}
                  className={cn(
                    "relative h-11 whitespace-nowrap px-4 text-xs font-semibold text-[#909399] tracking-wide",
                    alignClass[col.align ?? "left"],
                    stickyClass(col, true),
                  )}
                  style={cellStyle(col)}
                >
                  {col.title}
                  {colResizable && (
                    <span
                      role="separator"
                      aria-orientation="vertical"
                      className="absolute right-0 top-0 z-30 h-full w-[5px] cursor-col-resize select-none hover:bg-[#409EFF]/30 active:bg-[#409EFF]/50"
                      onMouseDown={(e) =>
                        onResizeStart(e, col.key, col.minWidth ?? DEFAULT_MIN_WIDTH)
                      }
                    />
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3.5 py-12 text-center text-sm text-[var(--el-text-placeholder)]"
              >
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map((record, rowIdx) => (
              <tr
                key={getRowKey(record, rowKey)}
                role={onRowClick ? "button" : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(record) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(record);
                        }
                      }
                    : undefined
                }
                className={cn(
                  "group/row border-b border-[#EBEEF5] transition-colors last:border-b-0 hover:bg-[#F5F7FA]/50",
                  onRowClick && "cursor-pointer",
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "h-[52px] overflow-hidden whitespace-nowrap px-4 text-[13px] text-[#606266]",
                      alignClass[col.align ?? "left"],
                      stickyClass(col, false),
                    )}
                    style={cellStyle(col)}
                  >
                    {(() => {
                      const useEllipsis = col.ellipsis ?? !col.render;
                      const node = col.render
                        ? col.render(getCellValue(record, col.key), record, rowIdx)
                        : String(getCellValue(record, col.key) ?? "");
                      return useEllipsis ? (
                        <OverflowTooltip>{node}</OverflowTooltip>
                      ) : (
                        node
                      );
                    })()}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
