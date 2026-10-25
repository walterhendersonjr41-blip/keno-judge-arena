import React from "react";
import useSWR from "swr";
import { api } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Microphone } from "@phosphor-icons/react";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function PressRoom() {
  const { data } = useSWR("/press?limit=40", fetcher, { refreshInterval: 5000 });
  return (
    <div>
      <PageHeader
        eyebrow="Neutral Statements"
        title="Press Room"
        subtitle="Judge AI publishes a short statement after every draw. Neutral, factual, cautious."
      />
      <div className="p-6 md:p-10 space-y-4" data-testid="press-list">
        {(data ?? []).map((p) => (
          <article key={p.id} className="border border-zinc-800 bg-[#111]">
            <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Microphone size={14} weight="bold" className="text-zinc-300" />
                <span className="font-heading uppercase font-bold text-sm">{p.headline}</span>
              </div>
              <div className="font-mono text-[10px] text-zinc-500">draw #{p.draw_number} · {p.mode}</div>
            </div>
            <div className="p-5 text-sm font-mono text-zinc-300 leading-relaxed">{p.body}</div>
          </article>
        ))}
        {!data?.length && <div className="text-sm text-zinc-500 font-mono">no statements yet — the Judge is silent.</div>}
      </div>
    </div>
  );
}
