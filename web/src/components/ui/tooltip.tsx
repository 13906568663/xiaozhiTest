"use client";

import {
  type ReactNode,
  type CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

type Placement = "top" | "bottom" | "left" | "right";

export type TooltipProps = {
  content: ReactNode;
  placement?: Placement;
  /** ms before showing */
  delay?: number;
  /** disable tooltip entirely */
  disabled?: boolean;
  className?: string;
  children: ReactNode;
};

const GAP = 6;

function computePosition(
  triggerRect: DOMRect,
  tipRect: DOMRect,
  placement: Placement,
): CSSProperties {
  let top = 0;
  let left = 0;

  switch (placement) {
    case "top":
      top = triggerRect.top - tipRect.height - GAP;
      left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
      break;
    case "bottom":
      top = triggerRect.bottom + GAP;
      left = triggerRect.left + (triggerRect.width - tipRect.width) / 2;
      break;
    case "left":
      top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
      left = triggerRect.left - tipRect.width - GAP;
      break;
    case "right":
      top = triggerRect.top + (triggerRect.height - tipRect.height) / 2;
      left = triggerRect.right + GAP;
      break;
  }

  left = Math.max(4, Math.min(left, window.innerWidth - tipRect.width - 4));
  top = Math.max(4, Math.min(top, window.innerHeight - tipRect.height - 4));

  return { position: "fixed", top, left };
}

export function Tooltip({
  content,
  placement = "top",
  delay = 200,
  disabled = false,
  className,
  children,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [style, setStyle] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = useCallback(() => {
    if (disabled) return;
    timerRef.current = setTimeout(() => setVisible(true), delay);
  }, [disabled, delay]);

  const hide = useCallback(() => {
    clearTimeout(timerRef.current);
    setVisible(false);
  }, []);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  useLayoutEffect(() => {
    if (!visible || !triggerRef.current || !tipRef.current) return;
    const pos = computePosition(
      triggerRef.current.getBoundingClientRect(),
      tipRef.current.getBoundingClientRect(),
      placement,
    );
    setStyle(pos);
  }, [visible, placement]);

  return (
    <>
      <div
        ref={triggerRef}
        className="inline-flex max-w-full"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {children}
      </div>
      {visible &&
        content != null &&
        content !== "" &&
        createPortal(
          <div
            ref={tipRef}
            role="tooltip"
            className={cn(
              "pointer-events-none z-[9999] max-w-xs rounded-md bg-[#303133] px-2.5 py-1.5 text-xs leading-relaxed text-white shadow-lg",
              "animate-in fade-in-0 zoom-in-95 duration-150",
              className,
            )}
            style={style}
          >
            {content}
          </div>,
          document.body,
        )}
    </>
  );
}

/**
 * Wraps children and shows a tooltip only when content overflows (horizontally or vertically).
 * Does NOT force single-line truncation — child content controls its own layout.
 */
export function OverflowTooltip({
  children,
  content: customContent,
  placement = "top",
  className,
}: {
  children: ReactNode;
  /** Override tooltip text. By default uses the element's textContent. */
  content?: ReactNode;
  placement?: Placement;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  const check = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setOverflowing(
      el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1,
    );
  }, []);

  const tipContent = customContent ?? (overflowing ? ref.current?.textContent : null);

  return (
    <Tooltip content={tipContent} placement={placement} disabled={!overflowing}>
      <div
        ref={ref}
        className={cn("w-full overflow-hidden", className)}
        onMouseEnter={check}
      >
        {children}
      </div>
    </Tooltip>
  );
}
