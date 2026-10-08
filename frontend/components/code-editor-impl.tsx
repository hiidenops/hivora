"use client";

import { indentLess, indentMore } from "@codemirror/commands";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { yaml } from "@codemirror/lang-yaml";
import { HighlightStyle, StreamLanguage, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { properties } from "@codemirror/legacy-modes/mode/properties";
import { Compartment, EditorState, Prec, type Extension } from "@codemirror/state";
import { EditorView, keymap, placeholder, type KeyBinding } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

import type { CodeEditorProps, CodeLanguage } from "./code-editor";

// Loaded on demand through ./code-editor: CodeMirror stays out of the pages' first bundle.

const LANGUAGES: Record<CodeLanguage, () => Extension> = {
  html, // with its <style> and <script> highlighted too
  css,
  js: javascript,
  yaml,
  properties: () => StreamLanguage.define(properties),
  text: () => [],
};

const INDENT = "  ";

/** Tab as in most editors: two spaces at the cursor; a selection's lines indented.
 *  Shift+Tab unindents. Escape then Tab leaves the editor (CodeMirror's own). */
const tab: KeyBinding = {
  key: "Tab",
  run: (view) => {
    if (view.state.selection.ranges.some((r) => !r.empty)) return indentMore(view);
    view.dispatch(view.state.update(view.state.replaceSelection(INDENT), { scrollIntoView: true, userEvent: "input" }));
    return true;
  },
  shift: indentLess,
};

// Colors from the theme (globals.css --code-*): they follow light and dark mode.
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword, t.modifier], color: "var(--code-keyword)" },
  { tag: [t.tagName, t.angleBracket], color: "var(--code-tag)" },
  { tag: [t.attributeName], color: "var(--code-attr)" },
  { tag: [t.string, t.attributeValue, t.special(t.string), t.regexp], color: "var(--code-string)" },
  { tag: [t.number, t.bool, t.null, t.atom, t.unit, t.color], color: "var(--code-number)" },
  { tag: [t.propertyName, t.className, t.labelName, t.definition(t.variableName)], color: "var(--code-property)" }, // + key of key=value
  { tag: t.quote, color: "var(--code-string)" }, // value of key=value
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.typeName], color: "var(--code-function)" },
  { tag: [t.comment, t.blockComment, t.lineComment, t.meta, t.documentMeta], color: "var(--code-comment)", fontStyle: "italic" },
  { tag: t.invalid, color: "var(--danger)" },
]);

const theme = EditorView.theme({
  "&": {
    backgroundColor: "var(--field)",
    color: "var(--foreground)",
    border: "1px solid var(--input)",
    borderRadius: "var(--radius-md, 0.375rem)",
    fontSize: "0.875rem",
    height: "100%", // the host's (resizable)
  },
  "&.cm-focused": { outline: "none", borderColor: "var(--ring)" },
  "&.cm-invalid": { borderColor: "var(--danger)" },
  ".cm-placeholder": { color: "var(--muted-foreground)" },
  // No ligatures: "<!--" and "-->" stay as typed, not arrows.
  ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.6", fontVariantLigatures: "none" },
  ".cm-content": { caretColor: "var(--foreground)", padding: "0.5rem 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--foreground)" },
  ".cm-gutters": { backgroundColor: "var(--card)", color: "var(--muted-foreground)", border: "none", borderRight: "1px solid var(--border)" },
  ".cm-activeLine": { backgroundColor: "color-mix(in oklch, var(--muted) 55%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--muted)", color: "var(--foreground)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "color-mix(in oklch, var(--primary) 30%, transparent)",
  },
  ".cm-matchingBracket, &.cm-focused .cm-matchingBracket": { backgroundColor: "color-mix(in oklch, var(--primary) 25%, transparent)", outline: "none" },
  ".cm-foldPlaceholder": { backgroundColor: "var(--muted)", border: "none", color: "var(--muted-foreground)" },
  ".cm-tooltip": { backgroundColor: "var(--card)", border: "1px solid var(--border)", color: "var(--foreground)" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "var(--muted)", color: "var(--foreground)" },
  ".cm-panels": { backgroundColor: "var(--card)", color: "var(--foreground)" },
});

/** A code editor: syntax colors per language, Tab indents (Escape then Tab leaves),
 *  Ctrl/Cmd+S calls `onSave`. Controlled: `value` replaces the text when it changes outside. */
export function CodeEditorImpl({ value, onChange, language, label, id, labelledBy, describedBy, invalid, placeholder: hint,
  readOnly = false, onSave, height = "28rem" }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView>(null);
  // The latest callbacks, read by the editor's handlers (created once).
  const handlers = useRef({ onChange, onSave });
  handlers.current = { onChange, onSave };
  // What a form field may change without a new editor (that would lose the cursor).
  const attributes = useRef(new Compartment());
  const attrs = (): Extension => [
    EditorView.contentAttributes.of({
      ...(id ? { id } : {}),
      ...(label ? { "aria-label": label } : {}),
      ...(labelledBy ? { "aria-labelledby": labelledBy } : {}),
      ...(describedBy ? { "aria-describedby": describedBy } : {}),
      ...(invalid ? { "aria-invalid": "true" } : {}),
      ...(readOnly ? { "aria-readonly": "true" } : {}),
    }),
    EditorView.editorAttributes.of(invalid ? { class: "cm-invalid" } : {}),
  ];

  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          Prec.highest(keymap.of([{ key: "Mod-s", preventDefault: true, run: () => (handlers.current.onSave?.(), true) }])),
          basicSetup,
          keymap.of([tab]),
          indentUnit.of(INDENT),
          EditorState.tabSize.of(2),
          LANGUAGES[language](),
          syntaxHighlighting(highlight),
          theme,
          hint ? placeholder(hint) : [],
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          attributes.current.of(attrs()),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) handlers.current.onChange(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => editor.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new editor only for a new language or mode
  }, [language, readOnly, hint]);

  // Labels and error state follow the form.
  useEffect(() => {
    view.current?.dispatch({ effects: attributes.current.reconfigure(attrs()) });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- attrs reads exactly these
  }, [id, label, labelledBy, describedBy, invalid, readOnly]);

  // A new text from outside (file read, reloaded, changes reverted, a suggestion picked).
  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === value) return;
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
  }, [value]);

  return <div ref={host} className="min-w-0 resize-y overflow-hidden rounded-md" style={{ height }} />;
}
