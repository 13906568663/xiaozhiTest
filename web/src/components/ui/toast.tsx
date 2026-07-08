"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle, XCircle, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "warning" | "info";

type ToastItem = {
  id: number;
  type: ToastType;
  message: string;
  leaving?: boolean;
};

const iconMap: Record<ToastType, typeof CheckCircle> = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const styleMap: Record<ToastType, { bg: string; border: string; icon: string }> = {
  success: {
    bg: "bg-[#F0F9EB]",
    border: "border-[#E1F3D8]",
    icon: "text-[#67C23A]",
  },
  error: {
    bg: "bg-[#FEF0F0]",
    border: "border-[#FDE2E2]",
    icon: "text-[#F56C6C]",
  },
  warning: {
    bg: "bg-[#FDF6EC]",
    border: "border-[#FAECD8]",
    icon: "text-[#E6A23C]",
  },
  info: {
    bg: "bg-[#F4F4F5]",
    border: "border-[#E9E9EB]",
    icon: "text-[#909399]",
  },
};

let _nextId = 0;
let _listener: ((t: ToastItem) => void) | null = null;

export function toast(type: ToastType, message: string) {
  _listener?.({ id: ++_nextId, type, message });
}

toast.success = (msg: string) => toast("success", msg);
toast.error = (msg: string) => toast("error", msg);
toast.info = (msg: string) => toast("info", msg);
toast.warning = (msg: string) => toast("warning", msg);

export function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 200);
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  useEffect(() => {
    _listener = (t) => {
      setItems((prev) => [...prev, t]);
      const timer = setTimeout(() => remove(t.id), 3000);
      timers.current.set(t.id, timer);
    };
    return () => {
      _listener = null;
    };
  }, [remove]);

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[9999] flex flex-col items-center gap-2 pt-5">
      {items.map((t, idx) => {
        const Icon = iconMap[t.type];
        const s = styleMap[t.type];
        return (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto flex items-center gap-2 rounded-md border px-4 py-2.5 shadow-sm transition-all duration-200",
              s.bg,
              s.border,
              t.leaving
                ? "translate-y-[-8px] opacity-0"
                : "translate-y-0 opacity-100",
            )}
            style={{
              animation: t.leaving ? undefined : "el-msg-in 0.2s ease-out",
              zIndex: 9999 - idx,
            }}
          >
            <Icon className={cn("size-[18px] shrink-0", s.icon)} />
            <span className="text-[13px] leading-snug text-[#606266]">{t.message}</span>
            <button
              type="button"
              onClick={() => remove(t.id)}
              className="ml-1 shrink-0 rounded p-0.5 text-[#C0C4CC] transition-colors hover:text-[#909399]"
            >
              <X className="size-3.5" />
            </button>
          </div>
        );
      })}
      <style>{`
        @keyframes el-msg-in {
          from { opacity: 0; transform: translateY(-16px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
