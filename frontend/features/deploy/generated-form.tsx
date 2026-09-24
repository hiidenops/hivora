"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useSession } from "@/components/app-shell";
import { api } from "@/lib/api/client";
import { Switch, Input, Label, Select } from "@/components/ui/input";
import { useI18n, type Localized, type MessageKey } from "@/lib/i18n";

export interface FieldDef {
  id: string;
  label: Localized;
  type: string;
  required?: boolean;
  default?: unknown;
  help?: Localized;
  pattern?: string;
  range?: [number, number];
  options?: { value: string | number; label: Localized }[];
  generate?: { length: number };
  showIf?: Record<string, unknown>;
  options_from?: string; // choices fetched from /options/<source>
  suggestions?: { value: string; description: Localized }[];
}

export type Values = Record<string, unknown>;

/** Defaults with `{{ }}` are rendered by the backend: leave the field empty. */
export function initialValues(fields: FieldDef[]): Values {
  const values: Values = {};
  for (const f of fields) {
    if (typeof f.default === "string" && f.default.includes("{{")) continue;
    if (f.default !== undefined && f.default !== null) values[f.id] = f.default;
    else if (f.type === "boolean") values[f.id] = false;
  }
  return values;
}

const INPUT_TYPE: Record<string, string> = {
  integer: "number",
  number: "number",
  port: "number",
  email: "email",
  url: "url",
  secret: "password",
};
const MONO = new Set(["port", "path", "url", "domain", "secret", "integer", "number"]);

/** Preview of a default like "Serveur {{ app.name }}"; other expressions stay hidden. */
function previewDefault(value: string, appName: string): string | undefined {
  const rendered = value.replace(/\{\{\s*app\.name\s*\}\}/g, appName);
  return rendered.includes("{{") ? undefined : rendered;
}

export function GeneratedForm({
  fields,
  values,
  errors,
  onChange,
  appName = "",
  secretsSet = [],
}: {
  fields: FieldDef[];
  values: Values;
  errors: Record<string, string>;
  onChange: (id: string, value: unknown) => void;
  appName?: string;
  secretsSet?: string[]; // editing: these secrets already have a value
}) {
  const { t, l } = useI18n();
  const visible = fields.filter((f) => !f.showIf || Object.entries(f.showIf).every(([k, v]) => values[k] === v));

  return (
    <div className="grid gap-4">
      {visible.map((f) => {
        const error = errors[f.id];
        const id = `field-${f.id}`;
        const hint =
          typeof f.default === "string" && f.default.includes("{{")
            ? previewDefault(f.default, appName)
            : undefined;
        const describe = [
          f.help ? `${id}-help` : null,
          error ? `${id}-error` : null,
        ].filter(Boolean).join(" ") || undefined;

        let control;
        if (f.type === "boolean") {
          control = (
            <label className="flex items-center gap-3 text-sm">
              <Switch
                id={id}
                checked={values[f.id] === true}
                onChange={(e) => onChange(f.id, e.target.checked)}
                aria-invalid={!!error}
                aria-describedby={describe}
              />
              <span>{l(f.label)}</span>
            </label>
          );
        } else if (f.type === "select") {
          control = (
            <Select
              id={id}
              value={String(values[f.id] ?? "")}
              onChange={(e) => {
                const opt = f.options?.find((o) => String(o.value) === e.target.value);
                onChange(f.id, opt?.value ?? e.target.value);
              }}
              aria-invalid={!!error}
              aria-describedby={describe}
            >
              {f.options?.map((o) => (
                <option key={String(o.value)} value={String(o.value)}>
                  {l(o.label)}
                </option>
              ))}
            </Select>
          );
        } else if (f.options_from) {
          control = (
            <DynamicSelect
              id={id}
              source={f.options_from}
              value={values[f.id] === undefined ? "" : String(values[f.id])}
              onChange={(v) => onChange(f.id, v)}
              invalid={!!error}
              describedBy={describe}
            />
          );
        } else if (f.type === "text") {
          control = (
            <textarea
              id={id}
              rows={5}
              className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-xs shadow-xs outline-none focus-visible:border-ring aria-invalid:border-danger"
              value={values[f.id] === undefined ? "" : String(values[f.id])}
              placeholder={hint}
              onChange={(e) => onChange(f.id, e.target.value === "" ? undefined : e.target.value)}
              aria-invalid={!!error}
              aria-describedby={describe}
            />
          );
        } else {
          const numeric = ["integer", "number", "port"].includes(f.type);
          control = (
            <Input
              id={id}
              type={INPUT_TYPE[f.type] ?? "text"}
              className={MONO.has(f.type) ? "font-mono" : undefined}
              value={values[f.id] === undefined ? "" : String(values[f.id])}
              placeholder={
                f.type === "secret" && secretsSet.includes(f.id)
                  ? t("edit.secretKept")
                  : f.type === "secret" && f.generate
                    ? t("deploy.secretGenerated")
                    : hint
              }
              min={f.range?.[0] ?? (f.type === "port" ? 1 : undefined)}
              max={f.range?.[1] ?? (f.type === "port" ? 65535 : undefined)}
              autoComplete={f.type === "secret" ? "new-password" : "off"}
              onChange={(e) => {
                const raw = e.target.value;
                onChange(f.id, raw === "" ? undefined : numeric ? Number(raw) : raw);
              }}
              aria-invalid={!!error}
              aria-describedby={describe}
            />
          );
        }

        return (
          <div key={f.id} className="grid gap-1.5">
            {f.type !== "boolean" && (
              <Label htmlFor={id}>
                {l(f.label)}
                {f.required && !(f.type === "secret" && secretsSet.includes(f.id)) && (
                  <span className="text-danger"> *</span>
                )}
              </Label>
            )}
            {control}
            {f.type === "text" && f.suggestions && f.suggestions.length > 0 && (
              <SuggestionPicker
                suggestions={f.suggestions}
                onPick={(line) => onChange(f.id, withLine(String(values[f.id] ?? ""), line))}
              />
            )}
            {f.help && (
              <p id={`${id}-help`} className="text-xs text-muted-foreground">
                {l(f.help)}
              </p>
            )}
            {error && (
              <p id={`${id}-error`} className="text-xs text-danger">
                {t(`field.${error}` as MessageKey)}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Replace the line with the same key ("key=..."), or append it. */
export function withLine(text: string, line: string): string {
  const key = line.split("=")[0];
  const lines = text.split("\n").filter((l) => l.trim() !== "");
  const i = lines.findIndex((l) => l.split("=")[0].trim() === key);
  if (i >= 0) lines[i] = line;
  else lines.push(line);
  return lines.join("\n");
}

function DynamicSelect({
  id,
  source,
  value,
  onChange,
  invalid,
  describedBy,
}: {
  id: string;
  source: string;
  value: string;
  onChange: (v: string) => void;
  invalid: boolean;
  describedBy?: string;
}) {
  const { advanced } = useSession();
  const { data } = useQuery({
    queryKey: ["options", source, advanced],
    queryFn: () => api<{ value: string; label: string }[]>(`/options/${source}`, { query: { snapshots: String(advanced) } }),
    staleTime: 3_600_000,
  });
  // The current value stays selectable even if the list does not offer it (yet).
  const options = data ?? [];
  const known = options.some((o) => o.value === value);
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={invalid} aria-describedby={describedBy} className="font-mono">
      {!known && value && <option value={value}>{value}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </Select>
  );
}

function SuggestionPicker({
  suggestions,
  onPick,
}: {
  suggestions: { value: string; description: Localized }[];
  onPick: (line: string) => void;
}) {
  const { t, l } = useI18n();
  const [filter, setFilter] = useState("");
  const q = filter.trim().toLowerCase();
  const shown = suggestions.filter((s) => !q || s.value.toLowerCase().includes(q) || l(s.description).toLowerCase().includes(q));
  return (
    <details className="rounded-md border">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t("form.suggestions")}</summary>
      <div className="grid gap-2 border-t p-3">
        <Input
          placeholder={t("form.suggestionsFilter")}
          aria-label={t("form.suggestionsFilter")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8"
        />
        <p className="text-xs text-muted-foreground">{t("form.suggestionsHint")}</p>
        <ul className="max-h-64 overflow-y-auto">
          {shown.map((s) => (
            <li key={s.value}>
              <button
                type="button"
                className="w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-muted"
                onClick={() => onPick(s.value)}
              >
                <code className="block font-mono text-xs">{s.value}</code>
                <span className="text-xs text-muted-foreground">{l(s.description)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}
