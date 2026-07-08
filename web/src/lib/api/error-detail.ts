/** FastAPI 等返回的 `detail` 字段转可读文案 */
export function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") {
          return String(item);
        }

        const record = item as { loc?: unknown; msg?: unknown };
        const location = Array.isArray(record.loc)
          ? record.loc
              .map((part) => String(part))
              .filter((part) => part !== "body")
              .join(".")
          : "";
        const msg = typeof record.msg === "string" ? record.msg : JSON.stringify(item);
        return location ? `${location}: ${msg}` : msg;
      })
      .filter(Boolean)
      .join("；");
  }

  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; detail?: unknown };
    if (typeof record.message === "string") {
      return record.message;
    }
    if (typeof record.detail === "string") {
      return record.detail;
    }
    return JSON.stringify(detail);
  }

  return String(detail ?? "");
}

export function messageFromResponseData(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const record = data as { detail?: unknown; message?: unknown };
  if (record.detail !== undefined) {
    const formatted = formatApiErrorDetail(record.detail);
    if (formatted) return formatted;
  }
  if (typeof record.message === "string") return record.message;
  return null;
}
