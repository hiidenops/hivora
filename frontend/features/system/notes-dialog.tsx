"use client";

import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
import { useI18n } from "@/lib/i18n";

/** A version's notes (CHANGELOG.md, Markdown) in a pop-up, Hivora's icon on top. */
export function NotesDialog({ open, onOpenChange, title, notes, done }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; notes: string; done?: string;
}) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl"
        closeLabel={t("common.close")}
        title={
          <span className="grid justify-items-center gap-3 pt-2 text-center">
            <img src="/icon.svg" alt="" className="size-16 rounded-2xl shadow-md" />
            {title}
          </span>
        }
      >
        <Markdown source={notes} className="max-h-[55vh] overflow-y-auto rounded-md border bg-background/60 p-4" />
        <DialogClose asChild>
          <Button className="justify-self-center">{done ?? t("common.close")}</Button>
        </DialogClose>
      </DialogContent>
    </Dialog>
  );
}
