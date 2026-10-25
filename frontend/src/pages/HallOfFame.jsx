import React from "react";
import useSWR from "swr";
import { api, AGENT_META } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Trophy } from "@phosphor-icons/react";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function HallOfFame() {
  const { data: hof } = useSWR("/hall-of-fame", fetcher, { refreshInterval: 10000 });
  const { data: h2h } = useSWR("/head-to-head", fetcher, { refreshInterval: 10000 });
  return (
    <div>
      <PageHeader
        eyebrow="Legends"
        title="Hall of Fame"
        subtitle="Immutable records. Only verified scored draws earn a plaque."
      />
      <div className="p-6 md:p-10 space-y-8">
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="hof-grid">
          {(hof ?? []).map((row) => {
            const meta = AGENT_META[row.ai_id];
            return (
              <div key={row.label} className="border border-zinc-800 bg-[#111] p-4">
                <div className="flex items-center gap-2">
                  <Trophy size={14} weight="fill" style={{ color: meta?.accent || "#F4F4F5" }} />
                  <div className="label-eyebrow">{row.label}</div>
                </div>
                <div className="mt-3 flex items-baseline justify-between">
                  <div className="font-heading uppercase text-sm">{row.display_name || "—"}</div>
                  <div className="stat-num text-2xl" style={{ color: meta?.accent }}>{row.value}</div>
                </div>
              </div>
            );
          })}
        </section>

        <section>
          <h2 className="font-heading text-lg font-bold uppercase tracking-tight mb-3">Head-to-Head</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="h2h-grid">
            {(h2h ?? []).map((p) => {
              const aMeta = AGENT_META[p.a]; const bMeta = AGENT_META[p.b];
              return (
                <div key={`${p.a}-${p.b}`} className="border border-zinc-800 bg-[#111] p-4">
                  <div className="label-eyebrow mb-3">{p.a_display} vs {p.b_display}</div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <div className="stat-num text-2xl" style={{ color: aMeta?.accent }}>{p.a_wins}</div>
                      <div className="label-eyebrow mt-1">A wins</div>
                    </div>
                    <div>
                      <div className="stat-num text-2xl text-zinc-400">{p.draws}</div>
                      <div className="label-eyebrow mt-1">draws</div>
                    </div>
                    <div>
                      <div className="stat-num text-2xl" style={{ color: bMeta?.accent }}>{p.b_wins}</div>
                      <div className="label-eyebrow mt-1">B wins</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
