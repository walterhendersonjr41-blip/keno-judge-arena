import React from "react";
import useSWR from "swr";
import { api, AGENT_META } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Scales, CheckCircle, XCircle } from "@phosphor-icons/react";
import KenoGrid from "../components/KenoGrid";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function JudgeConsole() {
  const { data: releases } = useSWR("/releases?limit=30", fetcher, { refreshInterval: 5000 });
  const { data: consensus } = useSWR("/consensus/recent?limit=15", fetcher, { refreshInterval: 5000 });

  const latest = releases?.[0];

  return (
    <div>
      <PageHeader
        eyebrow="Neutral Referee"
        title="Judge Console"
        subtitle="The Judge AI evaluates every prediction against future draws. Releases are rare and evidence-based — silence is the default."
      />
      <div className="p-6 md:p-10 space-y-8">
        {/* Latest decision */}
        <section className="border border-zinc-800 bg-[#111]">
          <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Scales size={14} weight="bold" className="text-zinc-300" />
              <span className="label-eyebrow">Latest Judgment</span>
            </div>
            {latest && (
              <span className="font-mono text-xs text-zinc-500">
                for draw #{latest.target_draw_number}
              </span>
            )}
          </div>
          {latest ? (
            <div className="p-5 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
              <div>
                <div className="flex items-center gap-3">
                  {latest.released ? (
                    <>
                      <CheckCircle size={20} weight="fill" className="text-emerald-400" />
                      <span className="font-heading font-black text-xl uppercase text-emerald-400">
                        Released
                      </span>
                    </>
                  ) : (
                    <>
                      <XCircle size={20} weight="fill" className="text-zinc-500" />
                      <span className="font-heading font-black text-xl uppercase text-zinc-400">
                        Withheld
                      </span>
                    </>
                  )}
                  <span className="ml-2 label-eyebrow">source: {latest.source}</span>
                </div>
                <p className="mt-4 text-sm text-zinc-300 font-mono leading-relaxed whitespace-pre-wrap">
                  {latest.reasoning}
                </p>
              </div>
              <div>
                <div className="label-eyebrow mb-2">Recommended Ticket</div>
                {latest.recommended_ticket ? (
                  <div className="border border-zinc-700 p-3">
                    <div className="label-eyebrow mb-2">
                      {latest.recommended_ticket.spots}-pick
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {latest.recommended_ticket.numbers.map((n) => (
                        <span key={n} className="border border-zinc-100 text-zinc-100 font-mono text-xs w-8 h-8 flex items-center justify-center">
                          {n}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-zinc-500 font-mono">no ticket released</div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-5 text-sm text-zinc-500 font-mono">awaiting first judgment...</div>
          )}
        </section>

        {/* Recent consensus */}
        <section>
          <h2 className="font-heading text-lg font-bold uppercase tracking-tight mb-3">
            Consensus Signal · last 15 draws
          </h2>
          <div className="border border-zinc-800 bg-[#111] overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  <th className="px-3 py-2 label-eyebrow text-left">Draw</th>
                  <th className="px-3 py-2 label-eyebrow text-right">Unanimous</th>
                  <th className="px-3 py-2 label-eyebrow text-right">Shared ≥2</th>
                  <th className="px-3 py-2 label-eyebrow text-right">Score</th>
                  <th className="px-3 py-2 label-eyebrow text-right">Hits</th>
                  <th className="px-3 py-2 label-eyebrow text-left">Unanimous set</th>
                </tr>
              </thead>
              <tbody>
                {(consensus ?? []).map((c) => (
                  <tr key={c.draw_number} className="border-b border-zinc-800">
                    <td className="px-3 py-2 text-zinc-100">#{c.draw_number}</td>
                    <td className="px-3 py-2 text-right">{c.unanimous_numbers.length}</td>
                    <td className="px-3 py-2 text-right">{c.consensus_numbers.length}</td>
                    <td className="px-3 py-2 text-right">{c.consensus_score}</td>
                    <td className="px-3 py-2 text-right text-emerald-400">{c.consensus_hits}</td>
                    <td className="px-3 py-2 text-zinc-400">{c.unanimous_numbers.join(", ") || "—"}</td>
                  </tr>
                ))}
                {!consensus?.length && (
                  <tr>
                    <td colSpan={6} className="px-3 py-6 text-center text-zinc-500">
                      no consensus records yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Release log */}
        <section>
          <h2 className="font-heading text-lg font-bold uppercase tracking-tight mb-3">
            Release Log
          </h2>
          <div className="border border-zinc-800 bg-[#111] divide-y divide-zinc-800" data-testid="release-log">
            {(releases ?? []).map((r) => (
              <div key={r.id} className="px-5 py-3 flex items-start gap-4">
                <span className="font-mono text-xs text-zinc-500 w-24 shrink-0">
                  #{r.target_draw_number}
                </span>
                <span className={`font-mono text-xs w-20 shrink-0 ${r.released ? "text-emerald-400" : "text-zinc-500"}`}>
                  {r.released ? "RELEASED" : "WITHHELD"}
                </span>
                <span className="font-mono text-xs text-zinc-400 flex-1">
                  {r.reasoning}
                </span>
              </div>
            ))}
            {!releases?.length && (
              <div className="px-5 py-6 text-center text-zinc-500 text-sm">no releases logged</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
