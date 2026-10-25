import React, { useState, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import useSWR from "swr";
import { api } from "../lib/api";
import {
  Broadcast, ChartBar, Scales, ClockCounterClockwise,
  Robot, Pulse, Trophy, Microphone, Warning, Target,
} from "@phosphor-icons/react";

const NAV = [
  { to: "/",            label: "Arena",       icon: Broadcast, testid: "nav-arena" },
  { to: "/leaderboard", label: "Leaderboard", icon: ChartBar,  testid: "nav-leaderboard" },
  { to: "/history",     label: "Draws",       icon: ClockCounterClockwise, testid: "nav-history" },
  { to: "/judge",       label: "Judge",       icon: Scales,    testid: "nav-judge" },
  { to: "/agents",      label: "Agents",      icon: Robot,     testid: "nav-agents" },
  { to: "/press",       label: "Press Room",  icon: Microphone, testid: "nav-press" },
  { to: "/hall",        label: "Hall of Fame",icon: Trophy,    testid: "nav-hall" },
  { to: "/picks",       label: "Judge Picks", icon: Target,    testid: "nav-picks" },
];

const fetcher = (u) => api.get(u).then((r) => r.data);

export default function Layout() {
  const loc = useLocation();
  const { data: sys, mutate } = useSWR("/system/status", fetcher, { refreshInterval: 5000 });
  const [switching, setSwitching] = useState(false);

  const toggleMode = async () => {
    if (!sys) return;
    const next = sys.current_mode === "live" ? "practice" : "live";
    setSwitching(true);
    try {
      await api.post("/system/mode", { mode: next });
      await mutate();
    } finally { setSwitching(false); }
  };

  const isLive = sys?.current_mode === "live";
  const feed = sys?.feed || {};

  return (
    <div className="min-h-screen flex text-zinc-100" style={{ background: "#050505" }}>
      <aside className="w-60 shrink-0 border-r border-zinc-800 flex flex-col">
        <div className="px-5 pt-6 pb-4 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <Pulse size={20} weight="bold" className="text-zinc-100" />
            <span className="font-heading text-sm font-black tracking-tight uppercase">
              Keno Duel AI
            </span>
          </div>
          <div className="label-eyebrow mt-2">Autonomous research lab</div>
        </div>
        <nav className="flex-1 py-3 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon, testid }) => (
            <NavLink key={to} to={to} end={to === "/"} data-testid={testid}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Icon size={14} weight="bold" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-zinc-800 px-5 py-4 space-y-2">
          <div className="label-eyebrow">Mode</div>
          <button
            onClick={toggleMode}
            disabled={switching}
            data-testid="mode-toggle"
            className="w-full border font-mono text-xs uppercase tracking-widest px-3 py-2 transition-colors"
            style={{
              borderColor: isLive ? "#4ADE80" : "#FACC15",
              color: isLive ? "#4ADE80" : "#FACC15",
              background: switching ? "#1a1a1a" : "transparent",
            }}>
            {isLive ? "● LIVE MODE" : "○ PRACTICE"}
          </button>
          <div className="label-eyebrow">Feed</div>
          <div className="font-mono text-[10px] text-zinc-500 space-y-0.5">
            <div>{feed.connected ? "● connected" : "○ disconnected"}</div>
            <div>attempts: {feed.attempts ?? 0}</div>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col" key={loc.pathname}>
        {isLive && (
          <div className="bg-emerald-900/20 border-b border-emerald-800/50 px-6 py-2 font-mono text-[10px] uppercase tracking-widest text-emerald-300 flex items-center gap-2">
            <span className="w-1.5 h-1.5 bg-emerald-400 animate-pulse" />
            LIVE MODE ACTIVE · scoring only against official TN Keno draws
          </div>
        )}
        <div className="flex-1">
          <Outlet />
        </div>
        <footer className="border-t border-zinc-800 px-6 py-3 text-[10px] font-mono text-zinc-500 flex items-center gap-2">
          <Warning size={12} weight="bold" className="text-zinc-500" />
          <span data-testid="disclaimer">
            Experimental research & entertainment system. No lottery winnings guaranteed. Predictions, if released, are not financial advice.
          </span>
        </footer>
      </main>
    </div>
  );
}
