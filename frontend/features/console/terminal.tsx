"use client";

// Loaded on demand only (next/dynamic): xterm never weighs on other pages.
import "@xterm/xterm/css/xterm.css";

import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef } from "react";

export interface TerminalHandle {
  write: (data: string) => void;
  focus: () => void;
}

export default function XTerm({
  onInput,
  onResize,
  onReady,
}: {
  onInput: (data: string) => void;
  onResize: (rows: number, cols: number) => void;
  onReady: (handle: TerminalHandle, size: { rows: number; cols: number }) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onInput, onResize });
  callbacks.current = { onInput, onResize };

  useEffect(() => {
    const term = new Terminal({
      fontFamily: '"JetBrains Mono Variable", ui-monospace, monospace',
      fontSize: 13,
      cursorBlink: true,
      convertEol: true,
      theme: { background: "#1d1713", foreground: "#efe8dc", cursor: "#efa831", selectionBackground: "#efa83155" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(box.current!);
    fit.fit();
    const input = term.onData((d) => callbacks.current.onInput(d));
    const resize = term.onResize(({ rows, cols }) => callbacks.current.onResize(rows, cols));
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(box.current!);
    onReady({ write: (d) => term.write(d), focus: () => term.focus() }, { rows: term.rows, cols: term.cols });
    term.focus();
    return () => {
      observer.disconnect();
      input.dispose();
      resize.dispose();
      term.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  return <div ref={box} className="size-full overflow-hidden rounded-md bg-[#1d1713] p-2" />;
}
