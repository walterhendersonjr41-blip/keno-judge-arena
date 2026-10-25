import React from "react";
import useSWR from "swr";
import { api } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Scales, CheckCircle, Clock } from "@phosphor-icons/react";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function JudgePicks() {
  const { data } = useSWR("/judge/picks?limit=100", fetcher, { refreshInterval: 8000 });
  const picks = data ?? [];
  const resolved = picks.filter((p) => p.resolved);
  const totalHits = resolved.reduce((s, p) => s + p.hit_count, 0);
  const totalSpots = resolved.reduce((s, p) => s + (p.spots || 0), 0);
  const hitRate = totalSpots ? ((totalHits / totalSpots) * 100).toFixed(1) : "0.0";

  return (
    <div>
      <PageHeader
        eyebrow="Verified Ledger"
        title="Judge Picks"
        subtitle="Every ticket the Judge has ever released — joined with what actually happened. No cherry-picking."
        right={
          <div className="border border-zinc-800 bg-[#111] px-4 py-2 flex gap-4">
            <div><div className="label-eyebrow">Releases</div><div className="stat-num text-lg">{picks.length}</div></div>
            <div><div className="label-eyebrow">Resolved</div><div className="stat-num text-lg">{resolved.length}</div></div>
            <div><div className="label-eyebrow">Hit Rate</div><div className="stat-num text-lg text-emerald-400">{hitRate}%</div></div>
          </div>
        }
      />
      <div className="p-6 md:p-10 space-y-4" data-testid="judge-picks-list">
        {picks.length === 0 && (
          <div className="border border-zinc-800 bg-[#111] p-8 text-center">
            <Scales size={32} weight="bold" className="mx-auto text-zinc-500" />
            <p className="mt-3 font-mono text-sm text-zinc-400">The Judge has released no picks yet.</p>
            <p className="mt-1 font-mono text-[10px] text-zinc-500">Silence is the default. This page fills only when evidence justifies a release.</p>
          </div>
        )}
        {picks.map((p) => {
          const wset = new Set(p.winning_numbers || []);
          return (
            <article key={p.target_draw_number} className="border border-zinc-800 bg-[#111]"
              data-testid={`judge-pick-${p.target_draw_number}`}>
              <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Scales size={14} weight="bold" className="text-emerald-400" />
                  <span className="font-heading font-black text-sm uppercase">Draw #{p.target_draw_number}</span>
                  <span className="label-eyebrow ml-2">via {p.source} · {p.spots}-pick</span>
                </div>
                {p.resolved ? (
                  <span className="flex items-center gap-2 font-mono text-xs text-emerald-400">
                    <CheckCircle size={14} weight="fill" /> {p.hit_count} / {p.spots} hits
                  </span>
                ) : (
                  <span className="flex items-center gap-2 font-mono text-xs text-yellow-400">
                    <Clock size={14} weight="bold" /> Pending draw
                  </span>
                )}
              </div>
              <div className="p-5">
                <div className="label-eyebrow mb-2">Picks vs Winning</div>
                <div className="flex flex-wrap gap-2 mb-4">
                  {p.picks.map((n) => {
                    const hit = wset.has(n);
                    return (
                      <span key={n} className="border-2 font-mono text-sm w-10 h-10 flex items-center justify-center"
                        style={hit ? { borderColor: "#4ADE80", background: "#4ADE80", color: "#050505" }
                                   : { borderColor: "#3f3f46", color: "#a1a1aa" }}>
                        {n}
                      </span>
                    );
                  })}
                </div>
                {p.resolved && (
                  <div className="text-[10px] font-mono text-zinc-500 mb-3">
                    Winning: {p.winning_numbers.join(" · ")}
                  </div>
                )}
                <p className="text-xs font-mono text-zinc-400 leading-relaxed">{p.reasoning}</p>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
