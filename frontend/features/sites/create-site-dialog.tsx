"use client";

import { useState, type FormEvent, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { useZones } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

import { useCreateSite } from "./hooks";

type Conflict = { port: number; protocol: string; used_by: string; suggestion: number | null };

/** Name, port and zone of a new site; its deploy and first page then run as jobs. */
export function CreateSiteDialog({ trigger, onJobs }: { trigger: ReactNode; onJobs: (jobIds: number[]) => void }) {
  const { t, errorMessage } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [port, setPort] = useState("");
  const [zone, setZone] = useState("");
  const { data: zones } = useZones();
  const create = useCreateSite();
  const conflicts =
    create.error instanceof ApiError && create.error.code === "port_conflict"
      ? ((create.error.details.conflicts as Conflict[] | undefined) ?? [])
      : [];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name: name.trim(), port: Number(port), zone: zone || null },
      {
        onSuccess: (created) => {
          setOpen(false);
          setName("");
          setPort("");
          onJobs([created.job.id, created.content_job.id]);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        create.reset();
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent title={t("sites.create")} closeLabel={t("common.close")}>
        <form className="grid gap-5" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="site-name">{t("sites.name")}</Label>
            <Input id="site-name" value={name} maxLength={100} required onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="site-port">{t("sites.port")}</Label>
            <Input id="site-port" type="number" min={1} max={65535} required value={port} className="max-w-40 font-mono" onChange={(e) => setPort(e.target.value)} />
            <p className="text-xs text-muted-foreground">{t("sites.portHelp")}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="site-zone">{t("sites.zone")}</Label>
            <Select id="site-zone" value={zone} onChange={(e) => setZone(e.target.value)}>
              <option value="">{t("dashboard.unclassified")}</option>
              {zones?.map((z) => (
                <option key={z.slug} value={z.slug}>
                  {z.name}
                </option>
              ))}
            </Select>
          </div>
          {conflicts.map((c) => (
            <Alert key={`${c.port}/${c.protocol}`} tone="danger">
              {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
              {c.suggestion !== null && (
                <Button type="button" variant="outline" size="sm" className="ml-2" onClick={() => setPort(String(c.suggestion))}>
                  {t("sites.useSuggested", { port: c.suggestion })}
                </Button>
              )}
            </Alert>
          ))}
          {create.error && conflicts.length === 0 && <Alert tone="danger">{errorMessage(create.error)}</Alert>}
          <Button type="submit" className="justify-self-end" disabled={create.isPending || !name.trim() || !port}>
            {t("sites.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
