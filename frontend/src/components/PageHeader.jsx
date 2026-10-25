import React from "react";

export function PageHeader({ eyebrow, title, subtitle, right }) {
  return (
    <div className="px-6 md:px-10 pt-8 pb-6 border-b border-zinc-800 flex items-end justify-between gap-6">
      <div>
        {eyebrow && <div className="label-eyebrow mb-2">{eyebrow}</div>}
        <h1 className="font-heading font-black text-3xl md:text-4xl tracking-tight uppercase text-zinc-100">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 text-sm text-zinc-400 max-w-2xl">{subtitle}</p>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
