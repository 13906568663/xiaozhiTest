"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { SkillEditor, type SkillEditorValue } from "@/components/skill/skill-editor";
import { parseSkillFrontmatter } from "@/components/skill/skill-frontmatter";
import { apiClient, ApiError } from "@/lib/api";

type SkillDetail = {
  id: string;
  code: string;
  description: string | null;
  source: string;
  status: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export default function SkillEditPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const skillId = params.id;

  const [loaded, setLoaded] = useState(false);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [value, setValue] = useState<SkillEditorValue>({ source: "", status: "active" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await apiClient.get<SkillDetail>(`/skills/${skillId}`);
        if (cancelled) return;
        setDetail(data);
        setValue({
          source: data.source,
          status: data.status === "inactive" ? "inactive" : "active",
        });
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "加载失败");
        router.replace("/skills");
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [skillId, router]);

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
      await apiClient.put(`/skills/${skillId}`, {
        source: value.source,
        status: value.status,
      });
      toast.success("保存成功");
      router.push("/skills");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-[var(--el-text-placeholder)]">
        加载中…
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-4 bg-[var(--el-bg-page)] px-7 py-6">
      <PageHeader
        title={`编辑技能 · ${detail?.code ?? ""}`}
        breadcrumb={[
          { label: "技能中心" },
          { label: "技能管理", href: "/skills" },
          { label: "编辑" },
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
