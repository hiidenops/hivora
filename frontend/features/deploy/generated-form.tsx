"use client";

import { Checkbox, Input, Label, Select } from "@/components/ui/input";
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
}: {
  fields: FieldDef[];
  values: Values;
  errors: Record<string, string>;
  onChange: (id: string, value: unknown) => void;
  appName?: string;
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
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                id={id}
                checked={values[f.id] === true}
                onChange={(e) => onChange(f.id, e.target.checked)}
                aria-invalid={!!error}
                aria-describedby={describe}
                className="mt-0.5"
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
        } else {
          const numeric = ["integer", "number", "port"].includes(f.type);
          control = (
            <Input
              id={id}
              type={INPUT_TYPE[f.type] ?? "text"}
              className={MONO.has(f.type) ? "font-mono" : undefined}
              value={values[f.id] === undefined ? "" : String(values[f.id])}
              placeholder={f.type === "secret" && f.generate ? t("deploy.secretGenerated") : hint}
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
                {f.required && <span className="text-danger"> *</span>}
              </Label>
            )}
            {control}
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
