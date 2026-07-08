import type { NavSection } from "@/components/admin/nav-types";

import { MENU_ICON_BY_NAME } from "./admin-menu-icons";

/**
 * 侧边栏导航结构。
 * 后端 `_DEFAULT_MENUS` (app/menu/services.py) 需同步更新。
 */
export const defaultAdminNavSections: NavSection[] = [
  {
    id: "chat",
    title: "对话中心",
    defaultOpen: true,
    items: [
      {
        href: "/chat/messages",
        label: "对话消息",
        icon: MENU_ICON_BY_NAME.MessageSquare,
      },
      {
        href: "/chat/config",
        label: "对话配置",
        icon: MENU_ICON_BY_NAME.Settings,
      },
    ],
  },
  {
    id: "capabilities",
    title: "工具能力中心",
    defaultOpen: true,
    items: [
      {
        href: "/capabilities/mcp",
        label: "MCP 工具",
        icon: MENU_ICON_BY_NAME.PlugZap,
      },
    ],
  },
  {
    id: "skills",
    title: "技能中心",
    defaultOpen: true,
    items: [
      {
        href: "/skills",
        label: "技能管理",
        icon: MENU_ICON_BY_NAME.Sparkles,
      },
    ],
  },
  {
    id: "knowledge",
    title: "知识管理中心",
    defaultOpen: true,
    items: [
      {
        href: "/knowledge/bases",
        label: "知识库管理",
        icon: MENU_ICON_BY_NAME.BookOpen,
      },
    ],
  },
  {
    id: "iam",
    title: "用户中心",
    defaultOpen: true,
    items: [
      {
        href: "/iam/users",
        label: "用户管理",
        icon: MENU_ICON_BY_NAME.Users,
      },
      {
        href: "/iam/roles",
        label: "角色管理",
        icon: MENU_ICON_BY_NAME.Shield,
      },
      {
        href: "/iam/permissions",
        label: "权限管理",
        icon: MENU_ICON_BY_NAME.ShieldCheck,
      },
    ],
  },
  {
    id: "admin",
    title: "管理中心",
    defaultOpen: true,
    items: [
      {
        href: "/admin/models",
        label: "模型管理",
        icon: MENU_ICON_BY_NAME.BrainCircuit,
      },
      {
        href: "/admin/memory",
        label: "记忆管理",
        icon: MENU_ICON_BY_NAME.Activity,
      },
      {
        href: "/admin/sessions",
        label: "会话管理",
        icon: MENU_ICON_BY_NAME.MessageCircle,
      },
    ],
  },
];
