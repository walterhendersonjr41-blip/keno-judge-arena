import React, { useMemo } from "react";
import useSWR from "swr";
import { useParams, Link } from "react-router-dom";
import { api, AGENT_META } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import PlayerAICard from "../components/PlayerAICard";

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function AIProfile() {
  const { ai_id } = useParams();
  const { data: agents } = useSWR("/agents", fetcher, { refreshInterval: 5000 });
  const { data } = useSWR(ai_id ? `/agents/${ai_id}` : null, fetcher, { refreshInterval: 5000 });
  const { data: h2hAll } = useSWR(ai_id ? "/head-to-head" : null, fetcher, { refreshInterval: 10000 });
  const { data: career } = useSWR(ai_id ? `/agents/${ai_id}/career?limit=25` : null, fetcher, { refreshInterval: 5000 });
  const { data: reflections } = useSWR(ai_id ? `/agents/${ai_id}/reflections?limit=10` : null, fetcher, { refreshInterval: 5000 });

  // Grid view of all agents when no id
  if (!ai_id) {
    return (
      <div>
        <PageHeader
          eyebrow="Roster"
          title="Player AIs"
          subtitle="Three independent competitors. Pick one to explore its dossier."
        />
        <div className="p-6 md:p-10 grid grid-cols-1 lg:grid-cols-3 gap-4">
          {(agents ?? []).map((s) => <PlayerAICard key={s.ai_id} stats={s} />)}
        </div>
      </div>
    );
  }

  const stats = data?.stats;
  const scores = data?.recent_scores ?? [];
  const meta = AGENT_META[ai_id];

  const chartData = useMemo(
    () => [...scores].reverse().map((s) => ({
      round: `#${s.draw_number}`,
      hits: s.total_hits,
      hitRate: Math.round(s.best_hit_rate * 100),
    })),
    [scores]
  );

  const myH2H = useMemo(
    () => (h2hAll ?? []).filter((p) => p.a === ai_id || p.b === ai_id),
    [h2hAll, ai_id]
  );

  if (!stats) {
    return <div className="p-10 text-zinc-500 font-mono text-sm">loading dossier...</div>;
  }

  return (
    <div>
      <PageHeader
        eyebrow={`Dossier · ${meta?.provider}`}
        title={stats.display_name}
        subtitle={`Model: ${stats.model_name}. This agent competes autonomously and cannot observe the picks of Alpha, Beta, or Gamma peers until the Judge resolves the draw.`}
        right={
          <Link
            to="/agents"
            data-testid="back-to-roster"
            className="border border-zinc-700 px-3 py-2 font-mono text-xs uppercase tracking-widest text-zinc-300 hover:bg-zinc-900"
          >
            ← Roster
          </Link>
        }
      />
      <div className="p-6 md:p-10 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <BigStat label="Reputation" value={Math.round(stats.reputation)} accent={meta?.accent} />
          <BigStat label="XP" value={stats.xp} />
          <BigStat label="Trophies" value={stats.trophies} />
          <BigStat label="Wins" value={stats.total_wins} color="#4ADE80" />
          <BigStat label="Losses" value={stats.total_losses} color="#EF4444" />
          <BigStat label="Streak" value={stats.current_streak} />
        </div>

        <div className="border border-zinc-800 bg-[#111] p-5">
          <div className="label-eyebrow mb-4">Confidence (dashed) & Hits (solid) — last rounds</div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <LineChart data={chartData}>
                <CartesianGrid stroke="#27272A" vertical={false} />
                <XAxis dataKey="round" stroke="#52525B" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
                <YAxis stroke="#52525B" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
                <Tooltip contentStyle={{ background: "#050505", border: "1px solid #27272A", fontFamily: "JetBrains Mono", fontSize: 11 }} />
                <Line type="linear" dataKey="hits" stroke={meta?.accent} strokeWidth={2} dot={{ r: 2, fill: meta?.accent }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="border border-zinc-800 bg-[#111] p-5">
            <div className="label-eyebrow mb-3">Research Notebook</div>
            {data?.notebook && Object.keys(data.notebook).length ? (
              <div className="space-y-2 text-xs font-mono">
                <div><span className="text-zinc-500">objective:</span> <span className="text-zinc-200">{data.notebook.objective || "—"}</span></div>
                <div><span className="text-zinc-500">hypothesis:</span> <span className="text-zinc-200">{data.notebook.hypothesis || "—"}</span></div>
                <div><span className="text-zinc-500">confidence:</span> <span className="text-zinc-200">{typeof data.notebook.confidence === "number" ? (data.notebook.confidence*100).toFixed(0)+"%" : "—"}</span></div>
                <div><span className="text-zinc-500">personality:</span> <span className="text-zinc-200">{data.personality} · {data.personality_tag}</span></div>
              </div>
            ) : <div className="text-xs text-zinc-500 font-mono">no notebook entries yet</div>}
          </div>
          <div className="border border-zinc-800 bg-[#111] p-5">
            <div className="label-eyebrow mb-3">Head-to-Head</div>
            <div className="space-y-2 text-xs font-mono">
              {myH2H.map(p => {
                const meAsA = p.a === ai_id;
                const myW = meAsA ? p.a_wins : p.b_wins;
                const oppW = meAsA ? p.b_wins : p.a_wins;
                const oppName = meAsA ? p.b_display : p.a_display;
                return (
                  <div key={`${p.a}-${p.b}`} className="flex items-center justify-between border-b border-zinc-800 pb-2">
                    <span className="text-zinc-400">vs {oppName}</span>
                    <span className="text-zinc-200">
                      <span className="text-emerald-400">{myW}W</span> · <span className="text-zinc-500">{p.draws}D</span> · <span className="text-rose-400">{oppW}L</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="border border-zinc-800 bg-[#111] p-5">
            <div className="label-eyebrow mb-3">Best Tickets</div>
            <div className="grid grid-cols-4 gap-3">
              {[5, 6, 7, 8].map((k) => (
                <div key={k} className="border border-zinc-800 p-3 text-center">
                  <div className="label-eyebrow">{k}-pick</div>
                  <div className="stat-num text-2xl mt-1">{stats[`best_${k}pick`] || 0}</div>
                  <div className="label-eyebrow mt-1 text-[10px]">of {k}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="border border-zinc-800 bg-[#111] p-5">
            <div className="label-eyebrow mb-3">Badges</div>
            <div className="flex flex-wrap gap-2">
              {(stats.badges || []).length === 0 && (
                <span className="text-zinc-500 font-mono text-xs">no badges unlocked</span>
              )}
              {(stats.badges || []).map((b) => (
                <span key={b} className="border font-mono text-[10px] uppercase tracking-widest px-2 py-1"
                      style={{ borderColor: meta?.accent, color: meta?.accent }}>
                  {b.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="border border-zinc-800 bg-[#111]">
          <div className="px-5 py-3 border-b border-zinc-800">
            <div className="label-eyebrow">Recent Rounds</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead className="text-zinc-500">
                <tr className="border-b border-zinc-800">
                  <th className="px-3 py-2 text-left label-eyebrow">Draw</th>
                  <th className="px-3 py-2 text-right label-eyebrow">5p</th>
                  <th className="px-3 py-2 text-right label-eyebrow">6p</th>
                  <th className="px-3 py-2 text-right label-eyebrow">7p</th>
                  <th className="px-3 py-2 text-right label-eyebrow">8p</th>
                  <th className="px-3 py-2 text-right label-eyebrow">Total</th>
                  <th className="px-3 py-2 text-right label-eyebrow">Result</th>
                  <th className="px-3 py-2 text-right label-eyebrow">XP</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => (
                  <tr key={s.id} className="border-b border-zinc-800">
                    <td className="px-3 py-2 text-zinc-100">#{s.draw_number}</td>
                    {[5, 6, 7, 8].map((k) => {
                      const ts = s.ticket_scores.find((t) => t.spots === k);
                      return <td key={k} className="px-3 py-2 text-right">{ts ? `${ts.hit_count}/${k}` : "—"}</td>;
                    })}
                    <td className="px-3 py-2 text-right text-zinc-100">{s.total_hits}</td>
                    <td className={`px-3 py-2 text-right ${s.result === "win" ? "text-emerald-400" : s.result === "draw" ? "text-yellow-400" : "text-rose-400"}`}>
                      {s.result}
                    </td>
                    <td className="px-3 py-2 text-right">{s.xp_awarded}</td>
                  </tr>
                ))}
                {!scores.length && (
                  <tr><td colSpan={8} className="px-3 py-6 text-center text-zinc-500">no rounds yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function BigStat({ label, value, color, accent }) {
  return (
    <div className="border border-zinc-800 bg-[#111] p-4">
      <div className="label-eyebrow">{label}</div>
      <div className="stat-num text-2xl mt-1" style={{ color: color || accent || "#F4F4F5" }}>
        {value}
      </div>
    </div>
  );
}
