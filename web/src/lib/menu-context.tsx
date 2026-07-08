"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { usePathname } from "next/navigation";

export type ApiMenuItem = {
  id: string;
  code: string;
  label: string;
  icon: string | null;
  href: string | null;
  menu_type: "group" | "item";
  default_expanded: boolean;
  children: ApiMenuItem[];
};

type MenuContextValue = {
  tree: ApiMenuItem[];
};

const MenuContext = createContext<MenuContextValue>({ tree: [] });

export function MenuProvider({
  tree,
  children,
}: {
  tree: ApiMenuItem[];
  children: ReactNode;
}) {
  const value = useMemo(() => ({ tree }), [tree]);
  return <MenuContext.Provider value={value}>{children}</MenuContext.Provider>;
}

type BreadcrumbMatch = {
  groupLabel: string;
  itemLabel: string;
  itemHref: string;
};

function findMenuItemByPath(
  tree: ApiMenuItem[],
  pathname: string,
): BreadcrumbMatch | null {
  for (const group of tree) {
    if (group.menu_type !== "group") continue;
    for (const item of group.children) {
      if (
        item.href &&
        (pathname === item.href || pathname.startsWith(item.href + "/"))
      ) {
        return {
          groupLabel: group.label,
          itemLabel: item.label,
          itemHref: item.href,
        };
      }
    }
  }
  return null;
}

/**
 * Returns dynamic breadcrumb items for the current page based on the menu tree.
 * Falls back to the provided static items when no menu match is found.
 */
export function useMenuBreadcrumb(
  staticItems?: { label: string; href?: string; current?: boolean }[],
) {
  const { tree } = useContext(MenuContext);
  const pathname = usePathname();

  return useMemo(() => {
    if (!staticItems || staticItems.length === 0) return staticItems;
    if (tree.length === 0) return staticItems;

    const match = findMenuItemByPath(tree, pathname);
    if (!match) return staticItems;

    const resolved = [...staticItems];
    if (resolved.length >= 1) {
      resolved[0] = { ...resolved[0], label: match.groupLabel };
    }
    if (resolved.length >= 2) {
      resolved[1] = { ...resolved[1], label: match.itemLabel };
    }
    return resolved;
  }, [staticItems, tree, pathname]);
}
