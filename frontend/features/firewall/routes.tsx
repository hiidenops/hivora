"use client";

import { useQuery } from "@tanstack/react-query";

import { TBody, TEmpty, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";

import { KEY, box } from "./host";

type Route = {
  dst: string;
  gateway: string | null;
  dev: string;
  protocol: string | null;
  scope: string | null;
  prefsrc: string | null;
  metric: number | null;
};
type Forward = {
  port: number;
  protocol: string;
  address: string;
  app: string;
  container_port: number;
};

export const useRoutes = () =>
  useQuery({
    queryKey: [...KEY, "routes"],
    queryFn: () => api<{ routes: Route[]; forwards: Forward[] }>("/host-firewall/routes"),
  });

/** Host routing table and Docker port forwards (read-only). */
export function Routes() {
  const { t } = useI18n();
  const { data } = useRoutes();
  return (
    <section className={box}>
      <h3 className="font-semibold">{t("fw.routes")}</h3>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.route.dst")}</Th>
            <Th>{t("fw.route.gateway")}</Th>
            <Th>{t("fw.route.dev")}</Th>
            <Th>{t("fw.route.src")}</Th>
            <Th numeric>{t("fw.route.metric")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.routes.map((r, i) => (
            <Tr key={i}>
              <Td mono>{r.dst}</Td>
              <Td mono>{r.gateway ?? "—"}</Td>
              <Td mono>{r.dev}</Td>
              <Td mono>{r.prefsrc ?? "—"}</Td>
              <Td numeric mono>
                {r.metric ?? "—"}
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
      <h3 className="mt-2 font-semibold">{t("fw.forwards")}</h3>
      <Table>
        <THead>
          <tr>
            <Th>{t("fw.forward.host")}</Th>
            <Th>{t("fw.forward.app")}</Th>
            <Th numeric>{t("fw.forward.container")}</Th>
          </tr>
        </THead>
        <TBody>
          {data?.forwards.length === 0 && <TEmpty colSpan={3}>{t("fw.noForward")}</TEmpty>}
          {data?.forwards.map((f) => (
            <Tr key={`${f.address}${f.port}${f.protocol}`}>
              <Td mono>
                {f.address}:{f.port}/{f.protocol}
              </Td>
              <Td>{f.app}</Td>
              <Td numeric mono>
                {f.container_port}
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </section>
  );
}
