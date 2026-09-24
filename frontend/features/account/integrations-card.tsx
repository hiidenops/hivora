"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { api, type Integrations } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

/** Admin: third-party keys. The saved value is never read back, only its presence. */
export function IntegrationsCard() {
  const { t, errorMessage } = useI18n();
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const { data } = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Integrations>("/system/integrations"),
  });
  const save = useMutation({
    mutationFn: (value: string) => api<void>("/system/integrations/curseforge", { method: "PUT", body: { key: value } }),
    onSuccess: () => {
      setKey("");
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      void qc.invalidateQueries({ queryKey: ["modpacks"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(key);
  };

  return (
    <form className="grid gap-3" onSubmit={submit}>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="cf-key">{t("settings.curseforge")}</Label>
        <span className={data?.curseforge_api_key_set ? "text-xs font-medium text-ok" : "text-xs text-muted-foreground"}>
          {data?.curseforge_api_key_set ? t("settings.curseforge.set") : t("settings.curseforge.unset")}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input
          id="cf-key"
          type="password"
          autoComplete="off"
          className="min-w-0 flex-1 font-mono"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={data?.curseforge_api_key_set ? t("edit.secretKept") : ""}
        />
        <Button type="submit" disabled={!key || save.isPending}>
          {t("common.save")}
        </Button>
        {data?.curseforge_api_key_set && (
          <Button type="button" variant="outline" disabled={save.isPending} onClick={() => save.mutate("")}>
            {t("settings.curseforge.remove")}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{t("settings.curseforge.help")}</p>
      {save.error && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    </form>
  );
}
