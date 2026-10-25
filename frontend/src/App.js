import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Layout from "@/components/Layout";
import Arena from "@/pages/Arena";
import Leaderboard from "@/pages/Leaderboard";
import DrawHistory from "@/pages/DrawHistory";
import JudgeConsole from "@/pages/JudgeConsole";
import AIProfile from "@/pages/AIProfile";
import PressRoom from "@/pages/PressRoom";
import HallOfFame from "@/pages/HallOfFame";
import JudgePicks from "@/pages/JudgePicks";
import "@/App.css";

const TOAST_OPTIONS = {
  style: {
    background: "#111",
    border: "1px solid #27272A",
    color: "#F4F4F5",
    fontFamily: "JetBrains Mono, monospace",
    fontSize: 12,
    borderRadius: 0,
  },
};

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Arena />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/history" element={<DrawHistory />} />
          <Route path="/judge" element={<JudgeConsole />} />
          <Route path="/agents" element={<AIProfile />} />
          <Route path="/agents/:ai_id" element={<AIProfile />} />
          <Route path="/press" element={<PressRoom />} />
          <Route path="/hall" element={<HallOfFame />} />
          <Route path="/picks" element={<JudgePicks />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <Toaster theme="dark" position="bottom-right" toastOptions={TOAST_OPTIONS} />
    </BrowserRouter>
  );
}

export default App;
