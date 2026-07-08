import { useCallback, useState } from "react";

/**
 * 轻量表单错误管理 hook。
 *
 * - `errors`：当前所有字段的错误消息。
 * - `setErrors`：整体设置（通常在 validate 时）。
 * - `clearErrors(...keys)`：清除指定字段的错误（在 onChange 里调用）。
 * - `hasErrors`：是否存在任何错误。
 */
export function useFormErrors() {
  const [errors, setErrors] = useState<Record<string, string>>({});

  const clearErrors = useCallback((...keys: string[]) => {
    if (keys.length === 0) return;
    setErrors((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const k of keys) {
        if (k in next) {
          delete next[k];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  const hasErrors = Object.keys(errors).length > 0;

  return { errors, setErrors, clearErrors, hasErrors } as const;
}
