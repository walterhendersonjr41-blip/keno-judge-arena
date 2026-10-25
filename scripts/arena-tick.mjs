// One arena tick, run by GitHub Actions every ~5 minutes (and runnable locally).
// Usage: node scripts/arena-tick.mjs <dataDir>
// Reads/writes <dataDir>/state.json. Real draws only; never invents a draw.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const E = require("../engine.js");

const DATA = process.argv[2] || "data";
const FILE = path.join(DATA, "state.json");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const LLM_URL = "https://text.pollinations.ai/openai";
const MAX = { draws: 400, rounds: 200, press: 60, releases: 60, reflections: 60, feedLog: 30 };
const AHEAD = 3; // seal tickets for the next 3 draws so a late cron run still has sealed tickets
const started = Date.now();
const budgetLeft = () => 210000 - (Date.now() - started); // keep each run under ~4 min
const nowIso = () => new Date().toISOString();

function load() {
  try { return JSON.parse(fs.readFileSync(FILE, "utf8")); } catch { }
  const stats = {}; E.AI_IDS.forEach(id => stats[id] = E.defaultStats(id));
  return { version: 1, created_at: nowIso(), stats, draws: [], predictions: {}, rounds: [], press: [], releases: [], reflections: [], feed: { attempts: 0, connected: false, last_error: null } };
}

async function fetchText(url, ms = 20000) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "text/html" }, signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.text();
  } finally { clearTimeout(t); }
}

async function fetchDraws(feed) {
  // The source occasionally serves an unrelated page (seen ~1 in 6 requests), so the direct route is retried.
  const direct = E.SOURCE_URL;
  const routes = [["direct", direct], ["direct", direct + "?r=2"], ["direct", direct + "?r=3"], ["direct", direct + "?r=4"],
    ["allorigins", "https://api.allorigins.win/raw?url=" + encodeURIComponent(E.SOURCE_URL)]];
  feed.attempts = (feed.attempts || 0) + 1; feed.last_check_at = nowIso();
  const errs = [];
  for (const [name, url] of routes) {
    try {
      const draws = E.parseCTL(await fetchText(url));
      if (draws.length) { Object.assign(feed, { connected: true, stale: false, last_success_at: feed.last_check_at, last_error: errs.length ? errs.join("; ") : null, route: name, source_url: E.SOURCE_URL }); return draws; }
      errs.push(name + ": no draws parsed");
    } catch (e) { errs.push(name + ": " + (e.message || e)); }
    await new Promise(r => setTimeout(r, 1500));
  }
  feed.last_error = errs.join("; ");
  Object.assign(feed, { connected: false, stale: true });
  return [];
}

let lastLlmAt = 0;
async function llm(system, user, seed, ms = 60000, retried = false) {
  if (budgetLeft() < 30000) throw new Error("time budget");
  const gap = 5000 - (Date.now() - lastLlmAt); if (gap > 0) await new Promise(res => setTimeout(res, gap)); // anonymous tier: keep calls spaced
  lastLlmAt = Date.now();
  ms = Math.min(ms, budgetLeft() - 15000); if (ms < 10000) throw new Error("time budget");
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
  let r;
  try {
    r = await fetch(LLM_URL, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: ctl.signal,
      body: JSON.stringify({ model: "openai", seed, reasoning_effort: "low", messages: [{ role: "system", content: system + " Think briefly; do not write long frequency tables. Output only what is asked." }, { role: "user", content: user }] }),
    });
    if (r.ok) { const j = await r.json(); return (j.choices?.[0]?.message?.content || "").trim(); }
  } finally { clearTimeout(t); }
  const body = (await r.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 160);
  if ((r.status === 402 || r.status === 429) && !retried && budgetLeft() > 75000) {
    console.log("LLM", r.status, "rate limited, waiting 20s:", body);
    await new Promise(res => setTimeout(res, 20000));
    return llm(system, user, seed, ms, true);
  }
  throw new Error("LLM HTTP " + r.status + " " + body);
}

function compactPrompt(id, target, draws, stats) {
  const last = [...draws].sort((a, b) => b.draw_number - a.draw_number).slice(0, 6)
    .map(d => "#" + d.draw_number + ": " + d.winning_numbers.join(",")).join("\n");
  return "Sealed Keno picks for Tennessee Keno draw #" + target + " (20 of 1..80 are drawn). Last draws:\n" + last +
    "\nYour lab status: rep " + Math.floor(stats.reputation) + ", streak " + stats.current_streak + ", rank " + stats.league_rank + (stats.in_recovery ? " (RECOVERY MODE: change approach)" : "") +
    "\nDo NOT count frequencies or analyze at length; pick by instinct in character. Tickets must not be subsets of each other. Return ONLY JSON: {\"reasoning\":\"2 sentences in character as " + E.AGENT_CONFIG[id].personality +
    "\",\"notebook\":{\"objective\":\"one line\",\"hypothesis\":\"one line\",\"confidence\":0.3},\"tickets\":[{\"spots\":5,\"numbers\":[5 unique]},{\"spots\":6,\"numbers\":[6]},{\"spots\":7,\"numbers\":[7]},{\"spots\":8,\"numbers\":[8]}]}";
}

async function predict(state, id, target) {
  const seed = (target * 7 + id.charCodeAt(0)) % 100000;
  const attempts = [
    [compactPrompt(id, target, state.draws, state.stats[id]), 40000, "compact"],
    [compactPrompt(id, target, state.draws, state.stats[id]), 40000, "compact-retry"],
  ];
  for (const [prompt, ms, mode] of attempts) {
    try {
      const text = await llm(E.AGENT_CONFIG[id].persona, prompt, mode === "compact" ? seed : seed + 1, ms);
      const p = E.extractJson(text); const tickets = p && E.validateTickets(p);
      if (tickets) return { reasoning: String(p.reasoning || "").slice(0, 1200), notebook: p.notebook || {}, tickets, prompt_mode: mode };
      console.log(id, mode, "parse fail");
    } catch (e) { console.log(id, mode, "LLM err", e.message); }
  }
  return E.fallbackPrediction(id, target);
}

async function main() {
  const state = load();
  const real = await fetchDraws(state.feed);
  const known = new Map(state.draws.map(d => [d.draw_number, d]));
  const now = nowIso();
  const newRounds = [];
  for (const rec of [...real].sort((a, b) => a.draw_number - b.draw_number)) {
    const dn = rec.draw_number;
    if (known.has(dn)) {
      const k = known.get(dn);
      if (JSON.stringify(k.winning_numbers) !== JSON.stringify(rec.winning_numbers)) k.mismatch = rec.winning_numbers;
      continue;
    }
    const preds = state.predictions[dn] ? Object.values(state.predictions[dn]) : [];
    const d = { draw_number: dn, winning_numbers: rec.winning_numbers, date: rec.date, first_seen_at: now, source: preds.length ? "LIVE" : "IMPORTED" };
    state.draws.push(d); known.set(dn, d);
    if (preds.length) {
      if (!state.feed.first_live_draw_number) { state.feed.first_live_draw_number = dn; state.feed.first_live_draw_at = now; }
      const r = E.scoreRound(d, preds, state.stats);
      const champ = E.updateChampion(state.stats);
      const round = { draw_number: dn, winning_numbers: d.winning_numbers, scored_at: now, ...r, events: r.events.concat(champ.events) };
      state.rounds.unshift(round); newRounds.push(round);
      preds.forEach(p => p.revealed = true);
    }
  }
  state.draws.sort((a, b) => b.draw_number - a.draw_number);
  const latest = state.draws[0]?.draw_number || 0;
  state.feed.latest_real_draw_number = real[0]?.draw_number || state.feed.latest_real_draw_number || null;

  // Seal tickets for the next draws (only targets the source has NOT published yet)
  if (latest) {
    for (let target = latest + 1; target <= latest + AHEAD; target++) {
      state.predictions[target] = state.predictions[target] || {};
      const todo = E.AI_IDS.filter(id => !state.predictions[target][id]);
      const results = []; for (const id of todo) results.push(await predict(state, id, target)); // sequential: anonymous tier rejects concurrent calls (HTTP 402)
      todo.forEach((id, i) => { state.predictions[target][id] = { ai_id: id, target_draw_number: target, sealed_at: nowIso(), revealed: false, ...results[i] }; });
    }
    // Judge release decision for the very next draw (once)
    const target = latest + 1;
    if (!state.releases.find(r => r.target_draw_number === target)) {
      const preds = Object.values(state.predictions[target] || {});
      const recent = {}; E.AI_IDS.forEach(id => { const s = state.stats[id]; recent[id] = { total_wins: s.total_wins, total_losses: s.total_losses, rounds_played: s.rounds_played, reputation: s.reputation, confidence: s.confidence, current_streak: s.current_streak, league_rank: s.league_rank, in_recovery: s.in_recovery, is_champion: s.is_champion }; });
      const con = E.computeConsensus(preds, []);
      let dec;
      try { const p = E.extractJson(await llm(E.JUDGE_PERSONA, E.judgeReleasePrompt(target, recent, con), target % 100000)) || {}; dec = { release: !!p.release, source: String(p.source || "none"), reasoning: String(p.reasoning || "Judge declined to elaborate.").slice(0, 1500) }; }
      catch (e) { dec = { release: false, source: "none", reasoning: "Judge unreachable (" + e.message + "). Default: withhold." }; }
      let ticket = null;
      if (dec.release) {
        if (dec.source === "consensus") { const picks = (con.unanimous_numbers.length ? con.unanimous_numbers : con.consensus_numbers).slice(0, 8); if (picks.length) ticket = { spots: picks.length, numbers: picks }; }
        else if (E.AI_IDS.includes(dec.source)) { const p = state.predictions[target][dec.source]; const t8 = p.tickets.find(t => t.spots === 8) || p.tickets[0]; ticket = { spots: t8.spots, numbers: t8.numbers }; }
      }
      state.releases.unshift({ target_draw_number: target, released: dec.release, source: dec.source, reasoning: dec.reasoning, recommended_ticket: ticket, created_at: nowIso() });
    }
  }
  // Judge press statement + private reflections, for the newest scored round only (cost guard like the backend)
  const lastRound = newRounds[newRounds.length - 1];
  if (lastRound && lastRound.played > 0) {
    const standings = E.AI_IDS.map(id => { const s = state.stats[id]; return { ai: s.display_name, rank: s.league_rank, wins: s.total_wins, losses: s.total_losses, streak: s.current_streak, reputation: Math.floor(s.reputation), champion: s.is_champion, recovery: s.in_recovery }; });
    let press = { headline: "Judge issues no comment.", body: "No further remarks." };
    try { const p = E.extractJson(await llm(E.JUDGE_PERSONA, E.pressPrompt(lastRound.draw_number, standings, E.AI_IDS.map(id => { const sc = lastRound.scores[id]; return E.AGENT_CONFIG[id].display_name + " this round: " + sc.result.toUpperCase() + " with " + sc.total_hits + " total hits"; }).concat(lastRound.events)), lastRound.draw_number % 100000)) || {}; press = { headline: String(p.headline || press.headline).slice(0, 140), body: String(p.body || press.body).slice(0, 600) }; }
    catch (e) { press = { headline: "Judge silent.", body: "Press feed unavailable (" + e.message + ")." }; }
    state.press.unshift({ draw_number: lastRound.draw_number, created_at: nowIso(), ...press });
    for (const id of E.AI_IDS) {
      const sc = lastRound.scores[id]; if (!sc || sc.result === "no_play") continue;
      const verb = sc.result === "win" ? "win" : sc.result === "loss" ? "lose" : "draw";
      let text;
      try { text = (await llm(E.AGENT_CONFIG[id].persona, `You just finished draw #${lastRound.draw_number}. Result: ${sc.result}. Total hits: ${sc.total_hits}. Write 2 short sentences PRIVATELY answering: why did I ${verb}? What will I try next? Stay in-character as ${E.AGENT_CONFIG[id].personality}. No JSON, plain text only.`, lastRound.draw_number % 1000 + 1)).slice(0, 400); }
      catch (e) { text = "(reflection unavailable: " + e.message + ")"; }
      state.reflections.unshift({ ai_id: id, draw_number: lastRound.draw_number, result: sc.result, text, at: nowIso() });
    }
  }

  // Grade released picks once their draw is known
  state.releases.forEach(r => { if (r.recommended_ticket && r.hits == null) { const d = known.get(r.target_draw_number); if (d) r.hits = E.scoreTicket(r.recommended_ticket, d.winning_numbers).hit_count; } });

  // Trim
  state.draws = state.draws.slice(0, MAX.draws);
  state.rounds = state.rounds.slice(0, MAX.rounds);
  state.press = state.press.slice(0, MAX.press);
  state.releases = state.releases.slice(0, MAX.releases);
  state.reflections = state.reflections.slice(0, MAX.reflections);
  const keepFrom = latest - 60;
  Object.keys(state.predictions).forEach(k => { if (+k < keepFrom) delete state.predictions[k]; });
  state.total_predictions = (state.total_predictions || 0);
  state.updated_at = nowIso();
  state.latest_draw_number = latest || null;
  state.next_target_draw = latest ? latest + 1 : null;
  fs.mkdirSync(DATA, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(state));
  console.log(`latest #${latest} · real ${real.length} · new rounds ${newRounds.length} · route ${state.feed.route} · err ${state.feed.last_error} · ${Date.now() - started}ms`);
  if (!real.length && !state.draws.length) process.exitCode = 0;
}
main().catch(e => { console.error(e); process.exit(1); });
