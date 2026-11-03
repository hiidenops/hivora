"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { readPref, writePref } from "@/lib/prefs";

import { NotesDialog } from "./notes-dialog";

/** Once per version and browser: what the installed version brings (the first visit, or
 *  the first one after an update). Closed: not shown again until the next version. */
export function WhatsNew() {
  const { t } = useI18n();
  const { data } = useQuery({
    queryKey: ["system-whats-new"],
    queryFn: () => api<{ version: string; notes: string | null }>("/system/whats-new"),
    staleTime: Infinity,
  });
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (data?.notes && readPref("whatsNew") !== data.version) setOpen(true);
  }, [data]);
  if (!data?.notes) return null;
  return (
    <NotesDialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) writePref("whatsNew", data.version);
      }}
      title={t("whatsNew.title", { version: data.version })}
      notes={data.notes}
      done={t("whatsNew.done")}
    />
  );
}
