import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { GridBackground } from "@/components/grid-background";
import { Providers } from "@/components/providers";

export const metadata: Metadata = { title: "Hivora" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <body>
        <GridBackground />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
