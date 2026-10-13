"use client";

import Link from "next/link";

import { Select } from "@/components/ui/input";
import { useApps } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** A field that links to a deployed app (a tool to its database): the apps of the allowed
 *  templates, "none" when optional, and where to deploy one when there is none yet. */
export function AppLinkSelect({
  id,
  templates,
  required,
  value,
  onChange,
  invalid,
  describedBy,
}: {
  id: string;
  templates: string[];
  required?: boolean;
  value: string;
  onChange: (v: string | undefined) => void;
  invalid: boolean;
  describedBy?: string;
}) {
  const { t } = useI18n();
  const { data } = useApps();
  const apps = (data ?? []).filter((a) => a.template && templates.includes(a.template));
  return (
    <>
      <Select id={id} value={value} onChange={(e) => onChange(e.target.value || undefined)} aria-invalid={invalid} aria-describedby={describedBy}>
        {(!required || !value) && <option value="">{t(required ? "form.appPick" : "form.appNone")}</option>}
        {value && !apps.some((a) => a.slug === value) && <option value={value}>{value}</option>}
        {apps.map((a) => (
          <option key={a.slug} value={a.slug}>
            {a.name}
          </option>
        ))}
      </Select>
      {data && apps.length === 0 && (
        <p className="text-xs text-muted-foreground">
          {t("form.appMissing")}{" "}
          {templates.map((tpl, i) => (
            <span key={tpl}>
              {i > 0 && ", "}
              <Link href={`/deploy/?template=${tpl}`} className="font-medium text-primary hover:underline">
                {t("form.appDeploy", { template: tpl })}
              </Link>
            </span>
          ))}
        </p>
      )}
    </>
  );
}
