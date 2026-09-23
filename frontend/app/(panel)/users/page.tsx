"use client";

import { MoreHorizontal, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { PageHeader, useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input, Label, Select } from "@/components/ui/input";
import type { Role, User } from "@/lib/api/client";
import { userApi, useUserMutation, useUsers } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

const ROLES: Role[] = ["admin", "operator", "viewer"];

function RoleSelect({ value, onChange, id }: { value: Role; onChange: (r: Role) => void; id?: string }) {
  const { t } = useI18n();
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value as Role)}>
      {ROLES.map((r) => (
        <option key={r} value={r}>
          {t(`role.${r}`)}
        </option>
      ))}
    </Select>
  );
}

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t, errorMessage } = useI18n();
  const [role, setRole] = useState<Role>("operator");
  const create = useUserMutation(userApi.create);
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    create.mutate(
      { username: String(f.get("username")), role, password: String(f.get("password")) },
      { onSuccess: () => onOpenChange(false) },
    );
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("users.add")} closeLabel={t("common.close")}>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="new-username">{t("users.username")}</Label>
            <Input id="new-username" name="username" required autoComplete="off" pattern="[a-z0-9][a-z0-9._\-]{1,63}" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-role">{t("users.role")}</Label>
            <RoleSelect id="new-role" value={role} onChange={setRole} />
            <p className="text-xs text-muted-foreground">{t(`role.${role}.help`)}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-password">{t("users.temporaryPassword")}</Label>
            <Input id="new-password" name="password" type="password" minLength={10} required autoComplete="new-password" />
            <p className="text-xs text-muted-foreground">{t("users.temporaryHint")}</p>
          </div>
          {create.error && <Alert tone="danger">{errorMessage(create.error)}</Alert>}
          <Button type="submit" disabled={create.isPending}>
            {t("users.add")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const { t, errorMessage } = useI18n();
  const reset = useUserMutation(userApi.resetPassword);
  return (
    <Dialog open={!!user} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t("users.resetPassword")} description={user?.username} closeLabel={t("common.close")}>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const temporary = String(new FormData(e.currentTarget).get("temporary"));
            if (user) reset.mutate({ id: user.id, temporary }, { onSuccess: onClose });
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="temporary">{t("users.temporaryPassword")}</Label>
            <Input id="temporary" name="temporary" type="password" minLength={10} required autoComplete="new-password" />
            <p className="text-xs text-muted-foreground">{t("users.temporaryHint")}</p>
          </div>
          {reset.error && <Alert tone="danger">{errorMessage(reset.error)}</Alert>}
          <Button type="submit" disabled={reset.isPending}>
            {t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function UsersPage() {
  const { t, lang, errorMessage } = useI18n();
  const { me, can } = useSession();
  const { data: users } = useUsers();
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<User | null>(null);
  const update = useUserMutation(userApi.update);
  const remove = useUserMutation(userApi.remove);
  const resetTotp = useUserMutation(userApi.resetTotp);
  const revoke = useUserMutation(userApi.revokeSessions);
  const error = update.error ?? remove.error ?? resetTotp.error ?? revoke.error;

  if (!can("admin")) return <Alert tone="danger">{t("error.insufficient_role")}</Alert>;

  return (
    <>
      <PageHeader
        title={t("users.title")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus /> {t("users.add")}
          </Button>
        }
      />
      {error && <Alert tone="danger" className="mb-4">{errorMessage(error)}</Alert>}
      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">{t("users.username")}</th>
              <th className="px-4 py-3 font-medium">{t("users.role")}</th>
              <th className="px-4 py-3 font-medium">{t("users.lastLogin")}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {users?.map((u) => (
              <tr key={u.id} className={u.disabled ? "opacity-60" : undefined}>
                <td className="px-4 py-3">
                  <span className="font-medium">{u.username}</span>
                  {u.id === me.id && <span className="ml-2 text-xs text-muted-foreground">({t("users.you")})</span>}
                  <span className="ml-2 inline-flex gap-1">
                    {u.disabled && <Badge>{t("users.disabled")}</Badge>}
                    {u.totp_enabled && <Badge>TOTP</Badge>}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <RoleSelect value={u.role} onChange={(role) => update.mutate({ id: u.id, role })} />
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString(lang) : t("users.never")}
                </td>
                <td className="px-4 py-3 text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" aria-label={t("users.actions", { name: u.username })}>
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      <DropdownMenuItem onSelect={() => setResetting(u)}>{t("users.resetPassword")}</DropdownMenuItem>
                      <DropdownMenuItem disabled={!u.totp_enabled} onSelect={() => resetTotp.mutate(u.id)}>
                        {t("users.resetTotp")}
                      </DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => revoke.mutate(u.id)}>{t("users.revokeSessions")}</DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={u.id === me.id}
                        onSelect={() => update.mutate({ id: u.id, disabled: !u.disabled })}
                      >
                        {u.disabled ? t("users.enable") : t("users.disable")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        disabled={u.id === me.id}
                        className="text-danger"
                        onSelect={() => {
                          if (window.confirm(t("users.deleteConfirm", { name: u.username }))) remove.mutate(u.id);
                        }}
                      >
                        {t("common.delete")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
    </>
  );
}
