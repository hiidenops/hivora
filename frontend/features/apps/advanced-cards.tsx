"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AppDetail } from "@/lib/api/client";
import { useAppCompose, useRevisions } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

const ComposeEditor = dynamic(() => import("@/features/apps/compose-editor").then((m) => m.ComposeEditor));
const RestoreButton = dynamic(() => import("@/features/apps/change-dialog").then((m) => m.RestoreButton));

/** Advanced mode of the app page: ports, containers, volumes, revisions, compose. */
export function AdvancedCards({ app, onJob }: { app: AppDetail; onJob: (id: number) => void }) {
  const { t, lang } = useI18n();
  const { can } = useSession();
  const setActiveJob = onJob;
  const { data: compose } = useAppCompose(app.id, true);
  const { data: revisions } = useRevisions(app.id, true);
  const [editingCompose, setEditingCompose] = useState(false);
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("app.ports")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-1 font-mono text-xs">
            {app.ports.map((p) => (
              <li key={`${p.service}-${p.container_port}-${p.protocol}`}>
                {p.host_port ? `${p.host_ip ?? "0.0.0.0"}:${p.host_port} → ` : ""}
                {p.service}:{p.container_port}/{p.protocol} ({p.exposure})
              </li>
            ))}
          </ul>
          <h4 className="mb-2 mt-4 text-sm font-medium">{t("app.containers")}</h4>
          <ul className="grid gap-1 text-xs">
            {app.containers.map((c) => (
              <li key={c.id} className="flex justify-between gap-2">
                <span className="font-mono">{c.name}</span>
                <span className="text-muted-foreground">
                  {c.state}
                  {c.health !== "none" && ` · ${c.health}`}
                </span>
              </li>
            ))}
          </ul>
          <h4 className="mb-2 mt-4 text-sm font-medium">{t("app.volumes")}</h4>
          <ul className="grid gap-1 font-mono text-xs">
            {app.volumes.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("app.revisions")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y text-sm">
            {revisions?.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                <span className="font-mono">
                  #{r.number}
                  {r.number === app.revision && <span className="ml-2 font-sans text-xs text-muted-foreground">{t("restore.current")}</span>}
                </span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {r.status} · {new Date(r.created_at).toLocaleString(lang)}
                </span>
                {can("operator") && r.restorable && r.number !== app.revision && (
                  <RestoreButton appId={app.id} number={r.number} onJob={setActiveJob} />
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      {compose && (
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between gap-3">
            <CardTitle>{t("app.compose")}</CardTitle>
            {can("admin") && !editingCompose && (
              <Button size="sm" variant="outline" onClick={() => setEditingCompose(true)}>
                {t("compose.edit")}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {editingCompose ? (
              <ComposeEditor appId={app.id} initial={compose.compose_yaml} onJob={setActiveJob} onClose={() => setEditingCompose(false)} />
            ) : (
              <CodeView code={compose.compose_yaml} />
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}
