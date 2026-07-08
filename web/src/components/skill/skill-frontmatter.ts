/**
 * 极简 SKILL.md frontmatter 解析器，避免引入 gray-matter / js-yaml 额外依赖。
 *
 * 仅支持简单的 `key: value` 行（值可带引号）。多行 YAML、列表、嵌套对象
 * 等高级特性不在 V1 范围内。后端解析采用 PyYAML 是权威校验，前端这里只为
 * 编辑时的实时预览提供"足够好"的反馈。
 */

const FRONTMATTER_RE = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*(?:\r?\n|$)/;
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

export type SkillFrontmatter = {
  name?: string;
  description?: string;
  raw: Record<string, string>;
};

export type FrontmatterParseResult =
  | {
      ok: true;
      meta: SkillFrontmatter;
      body: string;
      issues: string[];
    }
  | { ok: false; error: string };

function unquote(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2) {
    const first = trimmed[0];
    const last = trimmed[trimmed.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return trimmed.slice(1, -1);
    }
  }
  return trimmed;
}

export function parseSkillFrontmatter(source: string): FrontmatterParseResult {
  if (!source.trim()) {
    return { ok: false, error: "SKILL.md 内容为空" };
  }

  const match = source.match(FRONTMATTER_RE);
  if (!match) {
    return {
      ok: false,
      error: "缺少 frontmatter；SKILL.md 必须以 '---' 包裹 YAML 元信息开头",
    };
  }

  const rawMeta = match[1];
  const body = source.slice(match[0].length).replace(/^\r?\n+/, "");

  const raw: Record<string, string> = {};
  const lines = rawMeta.split(/\r?\n/);
  for (const line of lines) {
    if (!line.trim() || line.trim().startsWith("#")) continue;
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    const value = line.slice(colonIdx + 1);
    if (!key) continue;
    raw[key] = unquote(value);
  }

  const issues: string[] = [];
  const name = raw["name"];
  const description = raw["description"];

  if (!name) {
    issues.push("缺少 name 字段");
  } else if (!NAME_RE.test(name)) {
    issues.push("name 仅允许小写字母、数字、连字符，最长 64 字符");
  }
  if (!description) {
    issues.push("建议填写 description，帮助识别技能用途");
  }

  return {
    ok: true,
    meta: { name, description, raw },
    body,
    issues,
  };
}

export const DEFAULT_SKILL_TEMPLATE = `---
name: my-skill
description: 用一句话说明这个技能做什么、什么时候触发
---

# 技能标题

## 用途
描述这个技能在什么场景下使用。

## 步骤
1. 第一步
2. 第二步

## 注意事项
- 关键约束
`;
