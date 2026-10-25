import React, { useEffect, useState } from "react";
import useSWR from "swr";
import { api, AGENT_META } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import KenoGrid from "../components/KenoGrid";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function DrawHistory() {
  const { data: draws } = useSWR("/draws?limit=50", fetcher, { refreshInterval: 5000 });
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (!selected && draws && draws[0]) setSelected(draws[0].draw_number);
  }, [draws, selected]);

  const { data: detail } = useSWR(
    selected ? `/draws/${selected}` : null,
    fetcher
  );

  return (
    <div>
      <PageHeader
        eyebrow="Immutable Ledger"
        title="Draw History"
        subtitle="Every past draw, every prediction, every score. The receipts of the lab."
      />
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-0 border-t border-zinc-800">
        <aside className="border-r border-zinc-800 max-h-[calc(100vh-160px)] overflow-y-auto">
          {(draws ?? []).map((d) => (
            <button
              key={d.draw_number}
              onClick={() => setSelected(d.draw_number)}
              data-testid={`draw-row-${d.draw_number}`}
              className={`w-full text-left px-4 py-3 border-b border-zinc-800 hover:bg-[#111] transition-colors ${
                selected === d.draw_number ? "bg-[#111]" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-zinc-100">#{d.draw_number}</span>
                <span className="label-eyebrow" style={{ color: d.source === "LIVE" ? "#4ADE80" : d.source === "SIMULATED" ? "#FACC15" : "#A1A1AA" }}>{d.source}</span>
              </div>
              <div className="mt-1 font-mono text-[10px] text-zinc-500">
                {new Date(d.drawn_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </div>
              <div className="mt-0.5 font-mono text-[10px] text-zinc-600 truncate">
                {d.winning_numbers.slice(0, 10).join(" · ")}…
              </div>
            </button>
          ))}
        </aside>

        <section className="p-6 md:p-10">
          {!detail ? (
            <div className="text-sm text-zinc-500 font-mono">select a draw...</div>
          ) : (
            <>
              <div className="flex items-baseline justify-between mb-4">
                <h2 className="font-heading text-2xl font-black uppercase tracking-tight">
                  Draw #{detail.draw.draw_number}
                </h2>
                <div className="label-eyebrow">
                  {detail.draw.source} · <span className="text-zinc-300">{new Date(detail.draw.drawn_at).toISOString().replace('T',' ').slice(0,19)} UTC</span>
                </div>
              </div>

              <div className="border border-zinc-800 bg-[#111] p-5 mb-6">
                <div className="label-eyebrow mb-3">Winning Numbers</div>
                <KenoGrid winning={detail.draw.winning_numbers} testid="draw-winning-grid" />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {(detail.scores ?? []).map((sc) => {
                  const meta = AGENT_META[sc.ai_id];
                  const picks = sc.ticket_scores.flatMap((t) => t.numbers);
                  return (
                    <div key={sc.ai_id} className="border border-zinc-800 bg-[#111]" data-testid={`draw-ai-${sc.ai_id}`}>
                      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2" style={{ background: meta?.accent }} />
                          <span className="font-heading uppercase font-bold text-sm">{meta?.name}</span>
                        </div>
                        <span className={`font-mono text-xs ${sc.result === "win" ? "text-emerald-400" : sc.result === "draw" ? "text-yellow-400" : "text-rose-400"}`}>
                          {sc.result.toUpperCase()}
                        </span>
                      </div>
                      <div className="p-4">
                        <KenoGrid
                          winning={detail.draw.winning_numbers}
                          picks={picks}
                          accent={meta?.accent}
                          size="sm"
                        />
                      </div>
                      <div className="px-4 py-3 border-t border-zinc-800 grid grid-cols-4 gap-2">
                        {sc.ticket_scores.map((t) => (
                          <div key={t.spots} className="border border-zinc-800 p-2 text-center">
                            <div className="label-eyebrow">{t.spots}p</div>
                            <div className="stat-num text-sm mt-0.5" style={{ color: t.hit_count === t.spots ? "#4ADE80" : "#F4F4F5" }}>
                              {t.hit_count}/{t.spots}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="px-4 py-3 border-t border-zinc-800 text-xs font-mono text-zinc-400 flex justify-between">
                        <span>total hits</span><span className="stat-num text-zinc-100">{sc.total_hits}</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {detail.consensus && (
                <div className="mt-6 border border-zinc-800 bg-[#111] p-5">
                  <div className="label-eyebrow mb-2">Consensus Report</div>
                  <div className="grid grid-cols-4 gap-4 text-sm font-mono">
                    <div>
                      <div className="text-zinc-500">Unanimous</div>
                      <div className="text-zinc-100 text-lg mt-1">{detail.consensus.unanimous_numbers.length}</div>
                    </div>
                    <div>
                      <div className="text-zinc-500">Shared ≥2</div>
                      <div className="text-zinc-100 text-lg mt-1">{detail.consensus.consensus_numbers.length}</div>
                    </div>
                    <div>
                      <div className="text-zinc-500">Score</div>
                      <div className="text-zinc-100 text-lg mt-1">{detail.consensus.consensus_score}</div>
                    </div>
                    <div>
                      <div className="text-zinc-500">Consensus Hits</div>
                      <div className="text-emerald-400 text-lg mt-1">{detail.consensus.consensus_hits}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Predictions reasoning */}
              <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
                {(detail.predictions ?? []).map((p) => {
                  const meta = AGENT_META[p.ai_id];
                  return (
                    <div key={p.ai_id} className="border border-zinc-800 bg-[#111] p-4">
                      <div className="label-eyebrow mb-2" style={{ color: meta?.accent }}>{meta?.name} · reasoning</div>
                      <p className="text-xs text-zinc-400 font-mono leading-relaxed whitespace-pre-wrap">
                        {p.reasoning || "—"}
                      </p>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
