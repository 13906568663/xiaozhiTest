import type { LucideIcon } from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon?: LucideIcon;
};

export type NavSection = {
  id: string;
  title: string;
  items: NavItem[];
  /** When true, section starts expanded */
  defaultOpen?: boolean;
};
