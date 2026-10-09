"use client";

import { createContext, useContext } from "react";

/** The web servers whose apps can host sites: their name in messages and the volume of
 *  their main site (as the backend's sites.servers). */
export const SITE_SERVERS: Record<string, { label: string; folder: string }> = {
  nginx: { label: "nginx", folder: "html" },
  httpd: { label: "Apache", folder: "htdocs" },
};

/** Can this app (by its template) host sites? */
export const hostsSites = (template: string | null | undefined) => !!template && template in SITE_SERVERS;

/** The web server's name for the texts of a host's sites (its card, its site pages). */
export const ServerName = createContext("nginx");
export const useServerName = () => useContext(ServerName);
