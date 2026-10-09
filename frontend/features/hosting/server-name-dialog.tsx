"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import type { HostedSite } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { useSetServerName } from "./hooks";
import { useServerName } from "./server";

/** The domain name an added site answers to (advanced mode): nginx's files only, no restart. */
export function ServerNameDialog({ appId, site, open, onOpenChange, onJob }: {
  appId: number;
  site: HostedSite;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onJob: (jobId: number) => void;
}) {
  const { t, errorMessage } = useI18n();
  const server = useServerName();
  const [value, setValue] = useState(site.server_name ?? "");
  const save = useSetServerName(appId, site.id);
  const next = value.trim() || null; // empty: any name
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(next, {
      onSuccess: (job) => {
        onOpenChange(false);
        onJob(job.id);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("hosting.serverNameTitle", { name: site.name })} closeLabel={t("common.close")}>
        <form className="grid gap-5" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="site-server-name">{t("hosting.serverName")}</Label>
            <Input
              id="site-server-name"
              value={value}
              maxLength={253}
              className="font-mono"
              placeholder="blog.example.com"
              onChange={(e) => {
                setValue(e.target.value);
                save.reset();
              }}
            />
            <p className="text-xs text-muted-foreground">{t("hosting.serverNameHelp")}</p>
          </div>
          <p className="text-sm text-muted-foreground">{t("hosting.noRestart", { server })}</p>
          {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
          <Button type="submit" className="justify-self-end" disabled={save.isPending || next === site.server_name}>
            {t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
