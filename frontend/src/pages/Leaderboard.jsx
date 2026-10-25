import React from "react";
import useSWR from "swr";
import { api, AGENT_META } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Trophy, Medal } from "@phosphor-icons/react";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function Leaderboard() {
  const { data: rows } = useSWR("/leaderboard", fetcher, { refreshInterval: 5000 });
  const list = rows ?? [];
  const top = list[0];

  return (
    <div>
      <PageHeader
        eyebrow="Lifetime Standings"
        title="Leaderboard"
        subtitle="Ranked by lifetime score. Every win, every miss, every draw is permanently recorded."
      />
      <div className="p-6 md:p-10 space-y-6">
        {top && (
          <div className="border border-zinc-800 bg-[#111] p-5 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Trophy size={28} weight="fill" style={{ color: AGENT_META[top.ai_id]?.accent }} />
              <div>
                <div className="label-eyebrow">Current Leader</div>
                <div className="font-heading text-2xl font-black uppercase tracking-tight mt-1">
                  {top.display_name}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-6">
              <MetricBig label="Lifetime Score" value={top.lifetime_score} />
              <MetricBig label="Reputation" value={Math.round(top.reputation || 0)} />
              <MetricBig label="Titles" value={top.championship_titles || 0} />
            </div>
          </div>
        )}

        <div className="border border-zinc-800 bg-[#111] overflow-x-auto">
          <table className="w-full text-xs font-mono" data-testid="leaderboard-table">
            <thead className="text-zinc-500">
              <tr className="border-b border-zinc-800">
                <Th>Rank</Th><Th>AI</Th><Th>Model</Th>
                <Th right>Wins</Th><Th right>Losses</Th><Th right>Win %</Th>
                <Th right>Streak</Th><Th right>Longest</Th><Th right>Hit %</Th>
                <Th right>B5</Th><Th right>B6</Th><Th right>B7</Th><Th right>B8</Th>
                <Th right>XP</Th><Th right>Trophies</Th><Th right>Score</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => {
                const winPct = s.rounds_played ? ((s.total_wins / s.rounds_played) * 100).toFixed(1) : "0.0";
                const hitPct = s.total_ticket_spots ? ((s.total_hits / s.total_ticket_spots) * 100).toFixed(1) : "0.0";
                return (
                  <tr key={s.ai_id} className="border-b border-zinc-800 hover:bg-[#1a1a1a]" data-testid={`lb-row-${s.ai_id}`}>
                    <Td>#{s.rank}</Td>
                    <Td>
                      <span className="inline-flex items-center gap-2">
                        <span className="w-2 h-2" style={{ background: AGENT_META[s.ai_id]?.accent }} />
                        <span className="uppercase">{AGENT_META[s.ai_id]?.name}</span>
                      </span>
                    </Td>
                    <Td className="text-zinc-500">{s.model_name}</Td>
                    <Td right className="text-emerald-400">{s.total_wins}</Td>
                    <Td right className="text-rose-400">{s.total_losses}</Td>
                    <Td right>{winPct}%</Td>
                    <Td right className={s.current_streak > 0 ? "text-emerald-400" : s.current_streak < 0 ? "text-rose-400" : ""}>
                      {s.current_streak > 0 ? `+${s.current_streak}` : s.current_streak}
                    </Td>
                    <Td right>{s.longest_win_streak}</Td>
                    <Td right>{hitPct}%</Td>
                    <Td right>{s.best_5pick}</Td>
                    <Td right>{s.best_6pick}</Td>
                    <Td right>{s.best_7pick}</Td>
                    <Td right>{s.best_8pick}</Td>
                    <Td right>{s.xp}</Td>
                    <Td right>{s.trophies}</Td>
                    <Td right className="text-zinc-100">{s.lifetime_score}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Th({ children, right }) {
  return (
    <th className={`px-3 py-2 label-eyebrow ${right ? "text-right" : "text-left"} whitespace-nowrap`}>
      {children}
    </th>
  );
}
function Td({ children, right, className = "" }) {
  return <td className={`px-3 py-3 ${right ? "text-right" : ""} ${className}`}>{children}</td>;
}
function MetricBig({ label, value }) {
  return (
    <div className="text-right">
      <div className="label-eyebrow">{label}</div>
      <div className="stat-num text-xl mt-0.5">{value}</div>
    </div>
  );
}
