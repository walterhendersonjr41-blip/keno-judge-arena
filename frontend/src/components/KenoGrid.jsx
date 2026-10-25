import React from "react";

/**
 * Renders the 1..80 grid. Highlights `winning` (as base outline)
 * and `picks` mapped to a single accent color; a number that's both winning + picked is a "hit".
 */
export default function KenoGrid({ winning = [], picks = [], accent = "#F4F4F5", size = "md", testid }) {
  const winSet = new Set(winning);
  const pickSet = new Set(picks);
  const cellSize = size === "sm" ? "text-[10px]" : size === "lg" ? "text-sm" : "text-xs";
  return (
    <div className={`grid grid-cols-10 gap-1 ${cellSize}`} data-testid={testid}>
      {Array.from({ length: 80 }, (_, i) => i + 1).map((n) => {
        const isWin = winSet.has(n);
        const isPick = pickSet.has(n);
        const isHit = isWin && isPick;
        const style = isHit
          ? { background: accent, color: "#050505", borderColor: accent, boxShadow: `0 0 8px ${accent}55` }
          : isPick
          ? { color: accent, borderColor: accent }
          : isWin
          ? { color: "#F4F4F5", borderColor: "#F4F4F5", background: "#1a1a1a" }
          : {};
        return (
          <div key={n} className="keno-cell" style={style}>
            {n}
          </div>
        );
      })}
    </div>
  );
}
