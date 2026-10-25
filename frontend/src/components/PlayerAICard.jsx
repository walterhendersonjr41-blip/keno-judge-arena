import React from "react";
import { Link } from "react-router-dom";
import { AGENT_META } from "../lib/api";
import { Lock, Trophy, TrendUp, TrendDown, Minus, Crown, Warning } from "@phosphor-icons/react";

export default function PlayerAICard({ stats, liveSince, activity }) {
  if (!stats) return null;
  const meta = AGENT_META[stats.ai_id] || {};
  const winRate = stats.rounds_played ? (stats.total_wins / stats.rounds_played) * 100 : 0;
  const hitRate = stats.total_ticket_spots ? (stats.total_hits / stats.total_ticket_spots) * 100 : 0;
  const streak = stats.current_streak || 0;
  const StreakIcon = streak > 0 ? TrendUp : streak < 0 ? TrendDown : Minus;
  const streakColor = streak > 0 ? "#4ADE80" : streak < 0 ? "#EF4444" : "#A1A1AA";

  return (
    <Link to={`/agents/${stats.ai_id}`} data-testid={`player-card-${stats.ai_id}`}
      className="block border border-zinc-800 hover:border-zinc-600 transition-colors bg-[#111]">
      <div className="px-4 pt-4 pb-3 border-b border-zinc-800">
        {activity && (
          <div className="mb-2 flex items-center gap-2 border border-zinc-800 bg-black px-2 py-1">
            <span className="w-1 h-1 bg-emerald-400 animate-pulse shrink-0" />
            <span className="font-mono text-[9px] uppercase tracking-widest text-emerald-400 shrink-0">
              {activity.phase}
            </span>
            <span className="font-mono text-[10px] text-zinc-300 truncate">
              {activity.activity}
            </span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2" style={{ background: meta.accent }} />
            <span className="font-heading font-black text-lg tracking-tight uppercase">
              {stats.display_name}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {stats.is_champion && (
              <span className="border font-mono text-[9px] uppercase tracking-widest px-1.5 py-0.5 flex items-center gap-1"
                style={{ borderColor: meta.accent, color: meta.accent }}>
                <Crown size={10} weight="fill" /> CHAMP
              </span>
            )}
            {stats.in_recovery && (
              <span className="border border-rose-500 text-rose-400 font-mono text-[9px] uppercase tracking-widest px-1.5 py-0.5 flex items-center gap-1">
                <Warning size={10} weight="bold" /> RECOVERY
              </span>
            )}
          </div>
        </div>
        <div className="label-eyebrow mt-1" style={{ color: meta.accent }}>
          {stats.personality || meta.provider} · {stats.personality_tag || stats.model_name}
        </div>
        {liveSince && (
          <div className="mt-2 inline-flex items-center gap-1.5 border border-emerald-700 text-emerald-400 font-mono text-[9px] uppercase tracking-widest px-1.5 py-0.5">
            <span className="w-1 h-1 bg-emerald-400" />
            LIVE since {liveSince}
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 border-b border-zinc-800">
        <Cell label="Rank" value={stats.league_rank || "—"} accent={meta.accent} />
        <Cell label="Reputation" value={Math.round(stats.reputation || 0)} />
        <Cell label="Rounds" value={stats.rounds_played || 0} />
      </div>
      <div className="grid grid-cols-3 border-b border-zinc-800">
        <Cell label="Wins" value={stats.total_wins || 0} color="#4ADE80" />
        <Cell label="Losses" value={stats.total_losses || 0} color="#F87171" />
        <Cell label="No Play" value={stats.total_no_play || 0} color="#A1A1AA" />
      </div>
      <div className="grid grid-cols-3 border-b border-zinc-800">
        <Cell label="Win %" value={`${winRate.toFixed(1)}%`} />
        <Cell label="Hit %" value={`${hitRate.toFixed(1)}%`} />
        <div className="px-4 py-3 flex items-center gap-2">
          <StreakIcon size={14} weight="bold" style={{ color: streakColor }} />
          <div>
            <div className="label-eyebrow">Streak</div>
            <div className="stat-num text-base mt-0.5" style={{ color: streakColor }}>
              {streak > 0 ? `+${streak}` : streak}
            </div>
          </div>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-zinc-800 grid grid-cols-4 gap-2">
        {[5, 6, 7, 8].map((k) => (
          <div key={k} className="border border-zinc-800 p-2 text-center">
            <div className="label-eyebrow">B{k}</div>
            <div className="stat-num text-sm mt-0.5">{stats[`best_${k}pick`] || 0}</div>
          </div>
        ))}
      </div>

      <div className="px-4 py-3 flex items-start gap-2">
        <Lock size={12} weight="bold" className="text-zinc-500 mt-0.5" />
        <div className="flex-1">
          <div className="label-eyebrow">Mood</div>
          <div className="text-xs font-mono text-zinc-300 mt-0.5">{stats.mood || "—"}</div>
        </div>
        <Trophy size={14} weight="bold" style={{ color: meta.accent }} />
        <span className="stat-num text-xs">{stats.trophies || 0}</span>
      </div>
    </Link>
  );
}

function Cell({ label, value, color, accent }) {
  return (
    <div className="px-4 py-3 border-r border-zinc-800 last:border-r-0">
      <div className="label-eyebrow">{label}</div>
      <div className="stat-num text-base mt-0.5" style={{ color: color || accent || "#F4F4F5" }}>
        {value}
      </div>
    </div>
  );
}
