"use client";

import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { ApiError, type HostedSiteIn } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useAddSite, usePlanSite } from "./hooks";
import { RestartNotice } from "./restart-notice";

type Conflict = { port: number; protocol: string; used_by: string; suggestion: number | null };

/** A new site on its own port: checked first (conflicts, restart notice), then added. */
export function AddSiteDialog({ appId, disabled, onJob }: { appId: number; disabled: boolean; onJob: (jobId: number) => void }) {
  const { t, errorMessage } = useI18n();
  const { advanced } = useSession();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [port, setPort] = useState("");
  const [slug, setSlug] = useState("");
  const [serverName, setServerName] = useState("");
  const plan = usePlanSite(appId);
  const add = useAddSite(appId);
  const error = add.error ?? plan.error;
  const conflicts =
    error instanceof ApiError && error.code === "port_conflict"
      ? ((error.details.conflicts as Conflict[] | undefined) ?? [])
      : [];

  const body = (): HostedSiteIn => ({
    name: name.trim(),
    port: Number(port),
    slug: advanced && slug.trim() ? slug.trim() : null,
    server_name: advanced && serverName.trim() ? serverName.trim() : null,
  });
  const changed = (set: (v: string) => void) => (v: string) => {
    set(v);
    plan.reset();
    add.reset();
  };
  const reset = () => {
    setName("");
    setPort("");
    setSlug("");
    setServerName("");
    plan.reset();
    add.reset();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!plan.data) {
      plan.mutate(body());
      return;
    }
    add.mutate(body(), {
      onSuccess: (change) => {
        setOpen(false);
        reset();
        onJob(change.config_job.id);
      },
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" disabled={disabled}>
          <Plus /> {t("hosting.add")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("hosting.add")} closeLabel={t("common.close")}>
        <form className="grid gap-5" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="hosted-name">{t("hosting.name")}</Label>
            <Input id="hosted-name" value={name} maxLength={100} required onChange={(e) => changed(setName)(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="hosted-port">{t("hosting.port")}</Label>
            <Input id="hosted-port" type="number" min={1} max={65535} required value={port} className="max-w-40 font-mono" onChange={(e) => changed(setPort)(e.target.value)} />
            <p className="text-xs text-muted-foreground">{t("hosting.portHelp")}</p>
          </div>
          {advanced && (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="hosted-slug">{t("hosting.slug")}</Label>
                <Input id="hosted-slug" value={slug} maxLength={63} className="font-mono" placeholder={t("hosting.slugPlaceholder")} onChange={(e) => changed(setSlug)(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="hosted-server-name">{t("hosting.serverName")}</Label>
                <Input id="hosted-server-name" value={serverName} maxLength={253} className="font-mono" placeholder="blog.example.com" onChange={(e) => changed(setServerName)(e.target.value)} />
                <p className="text-xs text-muted-foreground">{t("hosting.serverNameHelp")}</p>
              </div>
            </>
          )}
          {conflicts.map((c) => (
            <Alert key={`${c.port}/${c.protocol}`} tone="danger">
              {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
              {c.suggestion !== null && (
                <Button type="button" variant="outline" size="sm" className="ml-2" onClick={() => changed(setPort)(String(c.suggestion))}>
                  {t("sites.useSuggested", { port: c.suggestion })}
                </Button>
              )}
            </Alert>
          ))}
          {error && conflicts.length === 0 && <Alert tone="danger">{errorMessage(error)}</Alert>}
          {plan.data && <RestartNotice plan={plan.data} />}
          <Button type="submit" className="justify-self-end" disabled={plan.isPending || add.isPending || !name.trim() || !port}>
            {plan.data ? t("hosting.addConfirm") : t("hosting.check")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
