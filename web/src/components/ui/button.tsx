import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded text-sm font-medium transition-colors outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4",
  {
    variants: {
      variant: {
        primary: "border border-transparent bg-[var(--el-primary)] text-white hover:bg-[var(--el-primary-hover)]",
        success: "border border-transparent bg-[var(--el-success)] text-white hover:bg-[var(--el-success-hover)]",
        warning: "border border-transparent bg-[var(--el-warning)] text-white hover:bg-[var(--el-warning-hover)]",
        danger: "border border-transparent bg-[var(--el-danger)] text-white hover:bg-[var(--el-danger-hover)]",
        secondary:
          "border border-[var(--el-border-base)] bg-[var(--el-fill-blank)] text-[var(--el-text-regular)] hover:border-[var(--el-primary)] hover:text-[var(--el-primary)]",
        ghost: "border border-transparent text-[var(--el-text-regular)] hover:bg-[var(--el-color-info-bg)]",
        link: "border-0 bg-transparent p-0 text-[var(--el-primary)] hover:underline",
        "link-success": "border-0 bg-transparent p-0 text-[var(--el-success)] hover:underline",
        "link-danger": "border-0 bg-transparent p-0 text-[var(--el-danger)] hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded px-3 text-xs",
        lg: "h-10 rounded px-5",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
