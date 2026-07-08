"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Copy, KeyRound, Shield, User } from "lucide-react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog } from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { toast } from "@/components/ui/toast";
import { apiClient, ApiError } from "@/lib/api";
import { persistAuthSession, readAuthSession, type AuthUser } from "@/lib/auth";
import { cn } from "@/lib/utils";

type ProfileUser = AuthUser & {
  last_login_at?: string | null;
};

type ApiKeyRow = {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
  is_active: boolean;
  created_at: string;
};

type ProfileResponse = {
  user: ProfileUser;
  api_keys: ApiKeyRow[];
};

function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function ProfilePage() {
  const session = readAuthSession();

  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const [displayName, setDisplayName] = useState("");
  const [basicSaving, setBasicSaving] = useState(false);
  const [basicError, setBasicError] = useState("");

  const [pwdOpen, setPwdOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwdErrors, setPwdErrors] = useState<Record<string, string>>({});
  const [pwdSaving, setPwdSaving] = useState(false);

  const [keyDialogOpen, setKeyDialogOpen] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deletingKeyId, setDeletingKeyId] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<ProfileResponse>("/profile");
      setProfile(data);
      setDisplayName(data.user.display_name ?? "");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "加载个人资料失败");
      const local = readAuthSession();
      if (local) {
        setProfile({ user: local.user as ProfileUser, api_keys: [] });
        setDisplayName(local.user.display_name ?? "");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const user = profile?.user ?? session?.user ?? null;

  const syncLocalDisplayName = useCallback((name: string) => {
    const s = readAuthSession();
    if (!s) return;
    persistAuthSession({
      ...s,
      user: { ...s.user, display_name: name },
    });
  }, []);

  const saveBasic = async () => {
    if (!user?.id) return;
    const next = displayName.trim();
    if (!next) {
      setBasicError("请输入显示名称");
      return;
    }
    setBasicError("");
    setBasicSaving(true);
    try {
      await apiClient.put(`/users/${user.id}`, { display_name: next });
      syncLocalDisplayName(next);
      await loadProfile();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败（可能需要用户管理权限）");
    } finally {
      setBasicSaving(false);
    }
  };

  const closePwd = () => {
    if (pwdSaving) return;
    setPwdOpen(false);
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setPwdErrors({});
  };

  const submitPwd = async () => {
    const next: Record<string, string> = {};
    if (!currentPassword) next.current_password = "请输入当前密码";
    if (!newPassword || newPassword.length < 8) next.new_password = "新密码至少 8 位";
    if (newPassword !== confirmPassword) next.confirm_password = "两次输入的新密码不一致";
    setPwdErrors(next);
    if (Object.keys(next).length > 0) return;

    setPwdSaving(true);
    try {
      await apiClient.put("/profile/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      closePwd();
      toast.success("密码修改成功");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "修改密码失败");
    } finally {
      setPwdSaving(false);
    }
  };

  const openCreateKey = () => {
    setKeyName("");
    setKeyDialogOpen(true);
  };

  const submitCreateKey = async () => {
    const name = keyName.trim();
    if (!name) {
      toast.error("请输入密钥名称");
      return;
    }
    setKeySaving(true);
    try {
      const { data } = await apiClient.post<{ plain_text_key: string }>("/profile/api-keys", { name });
      setKeyDialogOpen(false);
      setKeyName("");
      setCreatedKey(data.plain_text_key);
      setCopied(false);
      await loadProfile();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setKeySaving(false);
    }
  };

  const copyKey = async () => {
    if (!createdKey) return;
    try {
      await navigator.clipboard.writeText(createdKey);
      setCopied(true);
      toast.success("已复制到剪贴板");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("复制失败，请手动选中复制");
    }
  };

  const requestDeleteKey = (row: ApiKeyRow) => {
    setConfirmTarget({ id: row.id, name: row.name });
  };

  const handleConfirmDeleteKey = async () => {
    if (!confirmTarget) return;
    setDeletingKeyId(confirmTarget.id);
    try {
      await apiClient.delete(`/profile/api-keys/${confirmTarget.id}`);
      setConfirmTarget(null);
      await loadProfile();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeletingKeyId(null);
    }
  };

  const displayLabel = useMemo(() => {
    if (!user) return "";
    return user.display_name?.trim() || user.username;
  }, [user]);

  if (!session && !profile && loading) {
    return (
      <div className="flex items-center justify-center p-12 text-sm text-[var(--el-text-secondary)]">
        加载中…
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center p-12 text-sm text-[var(--el-text-secondary)]">
        未登录
      </div>
    );
  }

  const keys = profile?.api_keys ?? [];

  return (
    <div className="flex flex-col gap-5 bg-white px-7 py-6">
      <PageHeader title="个人中心" breadcrumb={[{ label: "用户中心" }, { label: "个人中心" }]} />

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        {/* 用户概览 */}
        <section className="flex items-center gap-5 rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <Avatar name={displayLabel} size={64} className="text-xl font-semibold" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5">
              <p className="text-lg font-semibold text-[var(--el-text-primary)]">{displayLabel}</p>
              {user.is_superuser && (
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">管理员</span>
              )}
              {user.status === "active" ? (
                <StatusBadge status="success" label="正常" />
              ) : (
                <StatusBadge status="danger" label="已禁用" />
              )}
            </div>
            <p className="mt-0.5 text-sm text-[var(--el-text-secondary)]">@{user.username}</p>
            <div className="mt-2 flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                {(user.roles ?? []).length === 0 ? (
                  <span className="text-xs text-[var(--el-text-placeholder)]">暂无角色</span>
                ) : (
                  user.roles.map((r) => (
                    <span
                      key={r.id}
                      className="rounded-full bg-[var(--el-primary-light-9)] px-2.5 py-0.5 text-[11px] text-[var(--el-primary)]"
                    >
                      {r.name}
                    </span>
                  ))
                )}
              </div>
              <span className="text-xs text-[var(--el-text-placeholder)]">
                最后登录：{formatDateTime(profile?.user?.last_login_at)}
              </span>
            </div>
          </div>
        </section>

        {/* 基本信息 */}
        <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <div className="mb-4 flex items-center gap-2">
            <User className="size-4 text-[var(--el-primary)]" />
            <h3 className="text-sm font-semibold text-[var(--el-text-primary)]">基本信息</h3>
          </div>
          <div className="flex flex-col gap-4">
            <FormField label="显示名称" error={basicError}>
              <Input
                value={displayName}
                onChange={(e) => {
                  setDisplayName(e.target.value);
                  if (basicError) setBasicError("");
                }}
                placeholder="请输入显示名称"
                disabled={loading}
              />
            </FormField>
            <FormField label="用户名">
              <Input value={user.username} disabled readOnly className="bg-[#F5F7FA]" />
            </FormField>
            <FormField label="角色">
              <div className="flex min-h-9 items-center rounded border border-[var(--el-border-lighter)] bg-[#F5F7FA] px-3 py-2 text-sm text-[var(--el-text-regular)]">
                {(user.roles ?? []).map((r) => r.name).join("、") || "—"}
              </div>
            </FormField>
            <div className="flex justify-end pt-1">
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={basicSaving || loading}
                onClick={() => void saveBasic()}
              >
                {basicSaving ? "保存中…" : "保存"}
              </Button>
            </div>
          </div>
        </section>

        {/* 安全设置 */}
        <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <div className="mb-4 flex items-center gap-2">
            <Shield className="size-4 text-[var(--el-primary)]" />
            <h3 className="text-sm font-semibold text-[var(--el-text-primary)]">安全设置</h3>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-[var(--el-border-lighter)] px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-[var(--el-text-primary)]">登录密码</p>
              <p className="mt-0.5 text-xs text-[var(--el-text-secondary)]">
                已设置，建议定期修改以保护账户安全
              </p>
            </div>
            <Button type="button" variant="secondary" size="sm" onClick={() => setPwdOpen(true)}>
              修改密码
            </Button>
          </div>
        </section>

        {/* API Key */}
        <section className="rounded-xl border border-[var(--el-border-lighter)] bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <KeyRound className="size-4 text-[var(--el-primary)]" />
              <h3 className="text-sm font-semibold text-[var(--el-text-primary)]">API Key</h3>
            </div>
            <Button type="button" variant="primary" size="sm" onClick={openCreateKey}>
              新建密钥
            </Button>
          </div>

          {keys.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--el-border-lighter)] bg-[#F8FAFF] px-4 py-6 text-center text-sm text-[var(--el-text-placeholder)]">
              暂无 API Key，点击上方按钮创建
            </div>
          ) : (
            <div className="divide-y divide-[var(--el-border-lighter)] rounded-lg border border-[var(--el-border-lighter)]">
              {keys.map((k) => (
                <div
                  key={k.id}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-[13px] font-medium text-[var(--el-text-primary)]">{k.name}</p>
                      {k.is_active ? (
                        <StatusBadge status="success" label="有效" />
                      ) : (
                        <StatusBadge status="warning" label="无效" />
                      )}
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-[var(--el-text-secondary)]">
                      {k.key_prefix} · 创建于 {formatDateTime(k.created_at)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="link-danger"
                    size="sm"
                    className="h-auto min-h-0 shrink-0 px-0 py-0 text-xs"
                    disabled={deletingKeyId === k.id}
                    onClick={() => requestDeleteKey(k)}
                  >
                    删除
                  </Button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* 修改密码弹窗 */}
      <Dialog
        open={pwdOpen}
        onClose={closePwd}
        title="修改密码"
        width={440}
        footer={
          <>
            <Button type="button" variant="secondary" size="sm" disabled={pwdSaving} onClick={closePwd}>
              取消
            </Button>
            <Button type="button" variant="primary" size="sm" disabled={pwdSaving} onClick={() => void submitPwd()}>
              {pwdSaving ? "提交中…" : "确认修改"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label="当前密码" required error={pwdErrors.current_password}>
            <Input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </FormField>
          <FormField label="新密码" required error={pwdErrors.new_password} hint="至少 8 位">
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          <FormField label="确认新密码" required error={pwdErrors.confirm_password}>
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
        </div>
      </Dialog>

      {/* 新建 API Key 弹窗 */}
      <Dialog
        open={keyDialogOpen}
        onClose={() => {
          if (!keySaving) setKeyDialogOpen(false);
        }}
        title="新建 API Key"
        width={400}
        footer={
          <>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={keySaving}
              onClick={() => !keySaving && setKeyDialogOpen(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={keySaving}
              onClick={() => void submitCreateKey()}
            >
              {keySaving ? "创建中…" : "创建"}
            </Button>
          </>
        }
      >
        <FormField label="名称" hint="用于区分用途，如 CI、本地开发">
          <Input
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder="请输入备注名称"
          />
        </FormField>
      </Dialog>

      {/* 密钥创建成功展示弹窗 */}
      <Dialog
        open={!!createdKey}
        onClose={() => setCreatedKey(null)}
        title="API Key 创建成功"
        width={520}
        footer={
          <Button type="button" variant="primary" size="sm" onClick={() => setCreatedKey(null)}>
            我已保存，关闭
          </Button>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[13px] leading-relaxed text-amber-700">
            请立即复制并妥善保存此密钥，关闭后将无法再次查看完整密钥。
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-[var(--el-border-lighter)] bg-[#F5F7FA] px-3.5 py-2.5">
            <code className="min-w-0 flex-1 break-all text-[13px] text-[var(--el-text-primary)]">
              {createdKey}
            </code>
            <button
              type="button"
              className={cn(
                "flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                copied
                  ? "bg-green-50 text-green-600"
                  : "bg-white text-[var(--el-text-regular)] hover:bg-[var(--el-primary-light-9)] hover:text-[var(--el-primary)]",
              )}
              onClick={() => void copyKey()}
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "已复制" : "复制"}
            </button>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={!!confirmTarget}
        title="确认删除"
        message={`确定删除「${confirmTarget?.name}」？`}
        confirmText="删除"
        variant="danger"
        onConfirm={() => void handleConfirmDeleteKey()}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
