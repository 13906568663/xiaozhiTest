"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { SkillEditor, type SkillEditorValue } from "@/components/skill/skill-editor";
import { DEFAULT_SKILL_TEMPLATE, parseSkillFrontmatter } from "@/components/skill/skill-frontmatter";
import { apiClient, ApiError } from "@/lib/api";

export default function SkillCreatePage() {
  const router = useRouter();
  const [value, setValue] = useState<SkillEditorValue>({
    source: DEFAULT_SKILL_TEMPLATE,
    status: "active",
  });
  const [saving, setSaving] = useState(false);

  const handleChange = useCallback((next: SkillEditorValue) => {
    setValue(next);
  }, []);

  const handleSave = async () => {
    const parsed = parseSkillFrontmatter(value.source);
    if (!parsed.ok) {
      toast.error(parsed.error);
      return;
    }
    if (!parsed.meta.name) {
      toast.error("frontmatter.name 必填");
      return;
    }

    setSaving(true);
    try {
      await apiClient.post("/skills", {
        source: value.source,
        status: value.status,
      });
      toast.success("新增成功");
      router.push("/skills");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-full flex-col gap-4 bg-[var(--el-bg-page)] px-7 py-6">
      <PageHeader
        title="新增技能"
        breadcrumb={[
          { label: "技能中心" },
          { label: "技能管理", href: "/skills" },
          { label: "新增技能" },
        ]}
        actions={
          <div className="flex items-center gap-2.5">
            <Button variant="secondary" size="sm" onClick={() => router.push("/skills")}>
              取消
            </Button>
            <Button variant="primary" size="sm" disabled={saving} onClick={() => void handleSave()}>
              {saving ? "保存中…" : "保存"}
            </Button>
          </div>
        }
      />

      <SkillEditor initial={value} onChange={handleChange} />
    </div>
  );
}
