import React, { useEffect, useState } from "react";
import useSWR from "swr";
import { api, AGENT_META } from "../lib/api";
import KenoGrid from "../components/KenoGrid";
import PlayerAICard from "../components/PlayerAICard";
import { PageHeader } from "../components/PageHeader";
import { toast } from "sonner";
import { Play, ArrowsClockwise, Broadcast } from "@phosphor-icons/react";

const fetcher = (url) => api.get(url).then((r) => r.data);

export default function Arena() {
  const { data: activity } = useSWR("/agents/activity", fetcher, { refreshInterval: 5000 });
  const { data: sys, mutate: mutSys } = useSWR("/system/status", fetcher, { refreshInterval: 5000 });
  const { data: agents, mutate: mutAgents } = useSWR("/agents", fetcher, { refreshInterval: 5000 });
  const { data: draws, mutate: mutDraws } = useSWR("/draws?limit=1", fetcher, { refreshInterval: 5000 });
  const { data: upcoming, mutate: mutUp } = useSWR("/predictions/upcoming", fetcher, { refreshInterval: 5000 });
  const { data: releases, mutate: mutRel } = useSWR("/releases?limit=1", fetcher, { refreshInterval: 5000 });
  const latestRelease = releases?.[0];

  const [triggering, setTriggering] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    const interval = sys?.interval_seconds ?? 60;
    setCountdown(interval);
    const t = setInterval(() => {
      setCountdown((c) => (c <= 1 ? interval : c - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [sys?.interval_seconds, sys?.latest_draw_number]);

  const triggerRound = async () => {
    setTriggering(true);
    try {
      await api.post("/system/trigger-round");
      toast.success("Round triggered — AIs are thinking...");
      setTimeout(() => {
        mutSys(); mutAgents(); mutDraws(); mutUp(); mutRel();
      }, 1500);
    } catch (e) {
      toast.error("Failed to trigger round");
    } finally {
      setTimeout(() => setTriggering(false), 1000);
    }
  };

  const lastDraw = draws?.[0];

  return (
    <div>
      <PageHeader
        eyebrow="Live Arena · 24/7"
        title="Keno Duel Arena"
        subtitle="Three independent AIs compete on every Tennessee Keno draw. Judge scores in real time. Predictions are sealed until the next draw resolves."
        right={
          <div className="flex items-center gap-3">
            <div className="border border-zinc-800 px-4 py-2 bg-[#111]">
              <div className="label-eyebrow">Next Draw In</div>
              <div className="stat-num text-2xl mt-0.5 text-zinc-100" data-testid="countdown-timer">
                {String(Math.floor(countdown / 60)).padStart(2, "0")}:
                {String(countdown % 60).padStart(2, "0")}
              </div>
            </div>
            <button
              data-testid="trigger-round-btn"
              onClick={triggerRound}
              disabled={triggering}
              className="border border-zinc-100 text-zinc-100 px-4 py-3 font-mono text-xs uppercase tracking-widest hover:bg-zinc-100 hover:text-black transition-colors disabled:opacity-40"
            >
              {triggering ? (
                <ArrowsClockwise size={14} weight="bold" className="inline animate-spin mr-2" />
              ) : (
                <Play size={14} weight="fill" className="inline mr-2" />
              )}
              Trigger Round
            </button>
          </div>
        }
      />

      <div className="p-6 md:p-10 space-y-8">
        {latestRelease?.released && latestRelease?.recommended_ticket && (
          <section
            data-testid="judge-pick-banner"
            className="border-2 p-6"
            style={{ borderColor: "#4ADE80", background: "linear-gradient(90deg, rgba(74,222,128,0.08), transparent)" }}
          >
            <div className="flex items-center gap-3">
              <span className="w-2 h-2 bg-emerald-400 animate-pulse" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-400">
                Judge Release · draw #{latestRelease.target_draw_number} · via {latestRelease.source}
              </span>
            </div>
            <h2 className="font-heading font-black text-2xl md:text-3xl uppercase tracking-tight mt-2 text-emerald-300">
              Judge's pick for the next draw
            </h2>
            <div className="mt-4 flex flex-wrap gap-2" data-testid="judge-pick-numbers">
              {latestRelease.recommended_ticket.numbers.map((n) => (
                <span
                  key={n}
                  className="border-2 border-emerald-400 text-emerald-300 font-mono text-lg w-12 h-12 flex items-center justify-center"
                  style={{ boxShadow: "0 0 12px rgba(74,222,128,0.35)" }}
                >
                  {n}
                </span>
              ))}
            </div>
            <p className="mt-4 text-xs font-mono text-zinc-400 max-w-3xl leading-relaxed">
              {latestRelease.reasoning}
            </p>
            <p className="mt-3 text-[10px] font-mono text-zinc-500">
              Not financial advice. Reality decides the winner.
            </p>
          </section>
        )}
        {/* Last draw + system status row */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 border border-zinc-800 bg-[#111]">
            <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Broadcast size={14} weight="bold" className="text-zinc-400" />
                <span className="label-eyebrow">Latest Official Draw</span>
              </div>
              <div className="font-mono text-xs text-zinc-500">
                {lastDraw ? `#${lastDraw.draw_number} · ${lastDraw.source}` : "awaiting..."}
              </div>
            </div>
            <div className="p-5" data-testid="latest-draw-panel">
              {lastDraw ? (
                <KenoGrid winning={lastDraw.winning_numbers} testid="latest-draw-grid" />
              ) : (
                <div className="text-sm text-zinc-500 py-10 text-center font-mono">
                  no draws yet — trigger the first round to seed the lab
                </div>
              )}
            </div>
          </div>

          <div className="border border-zinc-800 bg-[#111] p-5 space-y-4">
            <div>
              <div className="label-eyebrow">System</div>
              <div className="font-mono text-xs text-zinc-300 mt-1">
                {sys?.scheduler_running ? "● scheduler online" : "○ scheduler offline"}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Draws" value={sys?.total_draws ?? 0} />
              <Metric label="Predictions" value={sys?.total_predictions ?? 0} />
              <Metric label="Latest #" value={sys?.latest_draw_number ?? "—"} />
              <Metric label="Next #" value={sys?.next_target_draw ?? "—"} />
            </div>
            <div className="pt-3 border-t border-zinc-800">
              <div className="label-eyebrow">Judge Release</div>
              {latestRelease ? (
                <div className="mt-1 text-xs font-mono">
                  <span className={latestRelease.released ? "text-emerald-400" : "text-zinc-500"}>
                    {latestRelease.released ? "● RELEASED" : "○ withheld"}
                  </span>{" "}
                  <span className="text-zinc-500">
                    for #{latestRelease.target_draw_number} · src: {latestRelease.source}
                  </span>
                </div>
              ) : (
                <div className="mt-1 text-xs text-zinc-500 font-mono">no release yet</div>
              )}
            </div>
          </div>
        </section>

        {/* Player AIs */}
        <section>
          <div className="flex items-baseline justify-between mb-4">
            <h2 className="font-heading text-xl font-bold tracking-tight uppercase">
              Player AIs · Competitors
            </h2>
            <div className="label-eyebrow">Independent · No cross-agent visibility</div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {(agents ?? []).map((s) => {
              const up = (upcoming?.predictions || []).find((p) => p.ai_id === s.ai_id);
              const liveSince = sys?.feed?.first_live_draw_at
                ? new Date(sys.feed.first_live_draw_at).toISOString().slice(0, 10) +
                  ` · #${sys.feed.first_live_draw_number}`
                : null;
              return <PlayerAICard key={s.ai_id} stats={s} upcoming={up} liveSince={sys?.current_mode === "live" ? liveSince : null} activity={activity?.[s.ai_id]} />;
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="border border-zinc-800 p-2">
      <div className="label-eyebrow">{label}</div>
      <div className="stat-num text-base mt-0.5">{value}</div>
    </div>
  );
}
