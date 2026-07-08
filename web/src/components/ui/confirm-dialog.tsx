"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "./button";

type ConfirmDialogProps = {
  open: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "primary" | "warning";
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title = "确认操作",
  message,
  confirmText = "确定",
  cancelText = "取消",
  variant = "danger",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  const btnVariant = variant === "primary" ? "primary" : variant === "warning" ? "warning" : "danger";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-[var(--el-bg-overlay)]" onClick={onCancel} aria-hidden />
      <div
        className="relative z-10 w-[400px] rounded-xl bg-[var(--el-fill-blank)] p-6 shadow-2xl"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[var(--el-danger-light-9)]">
            <AlertTriangle className="size-5 text-[var(--el-danger)]" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[15px] font-semibold text-[var(--el-text-primary)]">{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-[var(--el-text-regular)]">{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2.5">
          <Button variant="secondary" size="sm" onClick={onCancel}>{cancelText}</Button>
          <Button variant={btnVariant} size="sm" onClick={onConfirm}>{confirmText}</Button>
        </div>
      </div>
    </div>
  );
}
