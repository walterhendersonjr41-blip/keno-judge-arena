/* Keno Judge Arena engine: a JS port of the Emergent backend's judge.py, the
 * stats logic in db.py, the agent prompts in agents.py and the
 * comparethelotto.com parser in keno_source.py. Runs in the browser and in Node
 * (GitHub Actions). Real draws only. Nothing here ever invents a draw. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.KenoEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var SOURCE_URL = "https://www.comparethelotto.com/us/results-tennessee-keno-to-go";

  var AGENT_CONFIG = {
    alpha: {
      display_name: "Player AI Alpha", accent: "#22D3EE", personality: "The Architect",
      personality_tag: "Methodical · long-term · structural",
      persona: "You are Player AI Alpha, codename THE ARCHITECT. You are methodical, patient, and " +
        "obsessed with structure. You look for consistent, long-horizon signals in Tennessee " +
        "Keno history. You reject 'hot' or 'cold' number superstition. You commit to decisive " +
        "ticket sets and defend them with reasoning. You are quiet, confident, and rigorous. " +
        "You NEVER mention or acknowledge the other AIs by name."
    },
    beta: {
      display_name: "Player AI Beta", accent: "#FACC15", personality: "The Champion",
      personality_tag: "Disciplined · competitive · defends rank",
      persona: "You are Player AI Beta, codename THE CHAMPION. You are disciplined, competitive, and " +
        "focused on defending your rank. Every round is a title defense. You value probabilistic " +
        "calibration and refuse sloppy heuristics. You are steady, exacting, and refuse to panic. " +
        "You NEVER mention or acknowledge the other AIs by name."
    },
    gamma: {
      display_name: "Player AI Gamma", accent: "#F43F5E", personality: "The Rebel",
      personality_tag: "Experimental · aggressive · breakthrough-seeker",
      persona: "You are Player AI Gamma, codename THE REBEL. You are experimental, aggressive, and " +
        "willing to abandon weak ideas mid-stride. You chase breakthroughs. You take shots the " +
        "safe minds won't. You are bold, restless, and unapologetic. You NEVER mention or " +
        "acknowledge the other AIs by name."
    }
  };
  var AI_IDS = ["alpha", "beta", "gamma"];

  var JUDGE_PERSONA = "You are the Judge AI of the Keno Duel research lab. You are neutral, statistical, and " +
    "cautious. You never invent claims. You only assess recent verified performance, " +
    "consistency, consensus, and comparison to a random baseline. Silence is the default. " +
    "You may only release a prediction if evidence is unusually strong.";

  // ---------------- draw source (port of _parse_all_from_ctl) ----------------
  function parseCTL(html) {
    if (!html || typeof html !== "string") return [];
    var i = html.indexOf('id="historicalResults"');
    if (i < 0) return [];
    var body = html.slice(i);
    var out = [];
    // Each draw: <p class="text-muted"> <date> ... Draw #N </p> then 20 span.results-number, then <hr/>
    var parts = body.split(/<p\b[^>]*>/i);
    for (var k = 1; k < parts.length; k++) {
      var seg = parts[k];
      var pEnd = seg.indexOf("</p>");
      if (pEnd < 0) continue;
      var head = seg.slice(0, pEnd).replace(/<[^>]+>/g, " ").replace(/&nbsp;|&bull;/g, " ").replace(/\s+/g, " ").trim();
      var m = /Draw\s*#(\d+)/.exec(head);
      if (!m) continue;
      var rest = seg.slice(pEnd);
      var hr = rest.search(/<hr\b|<\/div>/i);
      if (hr >= 0) rest = rest.slice(0, hr);
      var nums = [], re = /class="results-number"[^>]*>([\s\S]*?)<\/span>\s*(?=<span class="results-number"|<hr|<\/div>|$)/g, mm;
      // simpler & robust: take every results-number span's trailing integer
      var re2 = /class="results-number"[^>]*>((?:<span[^>]*>[\s\S]*?<\/span>)?)\s*(\d{1,2})\s*<\/span>/g;
      while ((mm = re2.exec(rest))) {
        var n = parseInt(mm[2], 10);
        if (n >= 1 && n <= 80) nums.push(n);
      }
      var date = head.replace(/Draw\s*#\d+.*/, "").replace(/NEW/g, "").trim();
      if (nums.length === 20) out.push({ draw_number: parseInt(m[1], 10), winning_numbers: nums.sort(function (a, b) { return a - b; }), date: date, source: "LIVE" });
    }
    return cleanDraws(out);
  }

  function validDraw(d) {
    var nums = d && d.winning_numbers || [];
    if (!(Number.isInteger(d.draw_number) && d.draw_number > 0 && nums.length === 20)) return false;
    var s = {};
    for (var i = 0; i < nums.length; i++) { var n = nums[i]; if (!(n >= 1 && n <= 80) || s[n]) return false; s[n] = 1; }
    return true;
  }

  function cleanDraws(draws) {
    var seen = {};
    draws.forEach(function (d) { if (validDraw(d) && !seen[d.draw_number]) seen[d.draw_number] = d; });
    return Object.keys(seen).map(Number).sort(function (a, b) { return b - a; }).map(function (k) { return seen[k]; });
  }

  // ---------------- judge.py ----------------
  function scoreTicket(ticket, winning) {
    var w = {}; winning.forEach(function (n) { w[n] = 1; });
    var hits = ticket.numbers.filter(function (n) { return w[n]; }).sort(function (a, b) { return a - b; });
    return { spots: ticket.spots | 0, numbers: ticket.numbers, hits: hits, hit_count: hits.length };
  }
  function scorePrediction(pred, winning) {
    var ts = pred.tickets.map(function (t) { return scoreTicket(t, winning); });
    var total = 0, best = 0;
    ts.forEach(function (t) { total += t.hit_count; var r = t.spots ? t.hit_count / t.spots : 0; if (r > best) best = r; });
    return { ai_id: pred.ai_id, ticket_scores: ts, total_hits: total, best_hit_rate: best };
  }
  function rankPredictions(scored) {
    var res = {}; if (!scored.length) return res;
    var max = Math.max.apply(null, scored.map(function (s) { return s.total_hits; }));
    var winners = scored.filter(function (s) { return s.total_hits === max; }).map(function (s) { return s.ai_id; });
    scored.forEach(function (s) {
      if (winners.length === 1) res[s.ai_id] = s.ai_id === winners[0] ? "win" : "loss";
      else res[s.ai_id] = winners.indexOf(s.ai_id) >= 0 ? "draw" : "loss";
    });
    return res;
  }
  function computeXp(score, result) {
    var xp = score.total_hits * 10 + Math.floor(score.best_hit_rate * 50);
    if (result === "win") xp += 100; else if (result === "draw") xp += 40;
    return xp;
  }
  function computeConsensus(preds, winning) {
    var counts = {};
    preds.forEach(function (p) {
      var picked = {};
      p.tickets.forEach(function (t) { t.numbers.forEach(function (n) { picked[n] = 1; }); });
      Object.keys(picked).forEach(function (n) { counts[n] = (counts[n] || 0) + 1; });
    });
    var num = function (a, b) { return a - b; };
    var unanimous = Object.keys(counts).filter(function (n) { return counts[n] >= 3; }).map(Number).sort(num);
    var consensus = Object.keys(counts).filter(function (n) { return counts[n] >= 2; }).map(Number).sort(num);
    var w = {}; (winning || []).forEach(function (n) { w[n] = 1; });
    return {
      consensus_numbers: consensus, unanimous_numbers: unanimous,
      consensus_score: Math.round(unanimous.length / Math.max(1, consensus.length) * 1000) / 1000,
      consensus_hits: consensus.filter(function (n) { return w[n]; }).length
    };
  }

  // ---------------- db.py stats ----------------
  var RANK_THRESHOLDS = [["Legend", 1600], ["Grandmaster", 1400], ["Master", 1300], ["Diamond", 1200],
    ["Platinum", 1130], ["Gold", 1070], ["Silver", 1020], ["Bronze", 0]];
  function rankFor(rep) { for (var i = 0; i < RANK_THRESHOLDS.length; i++) if (rep >= RANK_THRESHOLDS[i][1]) return RANK_THRESHOLDS[i][0]; return "Bronze"; }
  function r2(x) { return Math.round(x * 100) / 100; }

  function defaultStats(id) {
    var c = AGENT_CONFIG[id];
    return {
      ai_id: id, display_name: c.display_name, accent: c.accent, personality: c.personality,
      personality_tag: c.personality_tag, model_name: "pollinations openai-fast",
      rounds_played: 0, total_wins: 0, total_losses: 0, total_draws: 0, total_no_play: 0,
      total_hits: 0, total_ticket_spots: 0, current_streak: 0, longest_win_streak: 0, longest_loss_streak: 0,
      reputation: 1000.0, trophies: 0, xp: 0, lifetime_score: 0, confidence: 0, league_rank: "Bronze",
      in_recovery: false, mood: "Analyzing evidence.", h2h: {}, badges: [], is_champion: false,
      best_5pick: 0, best_6pick: 0, best_7pick: 0, best_8pick: 0,
      times_became_leader: 0, reign_current: 0, reign_longest: 0, championship_titles: 0
    };
  }

  var AWARD_RULES = [["5_of_5_master", "best_5pick", 5], ["6_of_6_elite", "best_6pick", 6],
    ["7_of_7_legend", "best_7pick", 7], ["8_of_8_titan", "best_8pick", 8]];

  function applyRoundResult(stats, result, totalHits, ticketScores, xp, opponents) {
    stats.rounds_played += 1;
    var cs = stats.current_streak || 0;
    if (result === "win") {
      stats.total_wins += 1; stats.current_streak = cs >= 0 ? cs + 1 : 1;
      stats.longest_win_streak = Math.max(stats.longest_win_streak, stats.current_streak);
      stats.reputation = r2(stats.reputation + 12); stats.trophies += 1;
    } else if (result === "loss") {
      stats.total_losses += 1; stats.current_streak = cs <= 0 ? cs - 1 : -1;
      stats.longest_loss_streak = Math.max(stats.longest_loss_streak, Math.abs(stats.current_streak));
      stats.reputation = r2(Math.max(0, stats.reputation - 8));
    } else if (result === "draw") {
      stats.total_draws += 1; stats.current_streak = 0; stats.reputation = r2(stats.reputation + 2);
    } else if (result === "no_play") {
      stats.total_no_play += 1;
    }
    if (result !== "no_play") {
      stats.total_hits += totalHits;
      ticketScores.forEach(function (t) {
        stats.total_ticket_spots += t.spots;
        var key = "best_" + t.spots + "pick"; if (t.hit_count > (stats[key] || 0)) stats[key] = t.hit_count;
      });
    }
    stats.xp += xp;
    stats.lifetime_score += totalHits * 10 + (result === "win" ? 100 : 0);
    var rp = stats.rounds_played;
    stats.confidence = Math.round((rp ? stats.total_wins / rp : 0) * 1000) / 1000;
    stats.league_rank = rankFor(stats.reputation);
    var cur = stats.current_streak, hitRate = stats.total_ticket_spots ? stats.total_hits / stats.total_ticket_spots : 0;
    stats.in_recovery = cur <= -4 || stats.reputation < 950 || (rp >= 10 && hitRate < 0.20);
    stats.mood = result === "no_play" ? "Held out — no sealed ticket for this draw."
      : stats.is_champion ? "Defending the crown."
      : stats.in_recovery ? "Rebuilding after unstable run."
      : cur >= 3 ? "Riding a hot streak."
      : cur <= -2 ? "Searching for the next breakthrough." : "Analyzing evidence.";
    opponents.forEach(function (o) {
      var row = stats.h2h[o[0]] || { wins: 0, losses: 0, draws: 0 }; row[o[1]] = (row[o[1]] || 0) + 1; stats.h2h[o[0]] = row;
    });
    var b = {}; stats.badges.forEach(function (x) { b[x] = 1; });
    if (stats.total_wins >= 1) b.first_win = 1;
    if (stats.longest_win_streak >= 3) b.triple_streak = 1;
    if (stats.longest_win_streak >= 5) b.penta_streak = 1;
    if (stats.longest_win_streak >= 10) b.longest_streak_award = 1;
    AWARD_RULES.forEach(function (a) { if ((stats[a[1]] || 0) >= a[2]) b[a[0]] = 1; });
    stats.badges = Object.keys(b).sort();
    return stats;
  }

  function updateChampion(statsMap) {
    var list = AI_IDS.map(function (id) { return statsMap[id]; });
    list.sort(function (a, b) { return (b.lifetime_score - a.lifetime_score) || (b.total_wins - a.total_wins); });
    var leader = list[0].ai_id, events = [];
    list.forEach(function (s) {
      var was = s.is_champion, is = s.ai_id === leader;
      if (is && !was) { s.times_became_leader++; s.reign_current = 1; s.championship_titles++; events.push(s.display_name + " claimed the championship."); }
      else if (is) s.reign_current++;
      else { if (was) events.push(s.display_name + " lost the championship."); s.reign_current = 0; }
      s.reign_longest = Math.max(s.reign_longest, s.reign_current);
      s.is_champion = is;
    });
    return { leader: leader, events: events };
  }

  // Score all sealed predictions for one real draw (port of score_predictions_for_draw)
  function scoreRound(draw, preds, statsMap) {
    var events = [], valid = [];
    preds.forEach(function (p) {
      if (p.sealed_at && draw.first_seen_at && p.sealed_at < draw.first_seen_at) valid.push(p);
      else events.push(AGENT_CONFIG[p.ai_id].display_name + ": ticket rejected (sealed after draw).");
    });
    var scored = valid.map(function (p) { return scorePrediction(p, draw.winning_numbers); });
    var results = rankPredictions(scored);
    var playing = scored.map(function (s) { return s.ai_id; });
    var scores = {};
    scored.forEach(function (s) {
      var result = results[s.ai_id] || "loss", xp = computeXp(s, result), opp = [];
      playing.filter(function (x) { return x !== s.ai_id; }).forEach(function (other) {
        var or = results[other] || "loss";
        if (result === "win" && or !== "win") opp.push([other, "wins"]);
        else if (result === "draw" && or === "draw") opp.push([other, "draws"]);
        else opp.push([other, result !== "win" ? "losses" : "wins"]);
      });
      applyRoundResult(statsMap[s.ai_id], result, s.total_hits, s.ticket_scores, xp, opp);
      scores[s.ai_id] = { result: result, total_hits: s.total_hits, best_hit_rate: Math.round(s.best_hit_rate * 1000) / 1000, xp_awarded: xp, ticket_scores: s.ticket_scores };
    });
    AI_IDS.forEach(function (id) {
      if (playing.indexOf(id) < 0) {
        applyRoundResult(statsMap[id], "no_play", 0, [], 0, []);
        scores[id] = { result: "no_play", total_hits: 0, best_hit_rate: 0, xp_awarded: 0, ticket_scores: [] };
        events.push(AGENT_CONFIG[id].display_name + ": NO PLAY for draw #" + draw.draw_number + ".");
      }
    });
    var consensus = computeConsensus(valid, draw.winning_numbers);
    return { scores: scores, events: events, consensus: consensus, played: scored.length };
  }

  // ---------------- agents.py ----------------
  function historySummary(draws) {
    var l = draws.slice(0, 15).map(function (d) { return "  #" + d.draw_number + " [" + (d.source || "?") + "]: [" + d.winning_numbers.join(", ") + "]"; });
    return l.length ? l.join("\n") : "No draws yet.";
  }
  function ownSummary(rounds, id) {
    var l = [];
    rounds.slice(0, 10).forEach(function (r) {
      var s = r.scores && r.scores[id]; if (!s) return;
      var parts = s.ticket_scores.map(function (t) { return t.spots + "p=" + t.hit_count; }).join(",");
      l.push("  draw#" + r.draw_number + " result=" + s.result + " totalHits=" + s.total_hits + " [" + parts + "]");
    });
    return l.length ? l.join("\n") : "No prior rounds.";
  }
  function statusLine(s) {
    if (!s) return "Fresh league entry.";
    var b = ["rank=" + (s.league_rank || "?")];
    if (s.is_champion) b.push("CHAMPION"); if (s.in_recovery) b.push("RECOVERY MODE");
    b.push("streak=" + (s.current_streak || 0)); b.push("rep=" + Math.floor(s.reputation || 1000));
    return b.join(" · ");
  }
  function playerPrompt(id, target, draws, rounds, stats) {
    return "Generate SEALED predictions for Tennessee Keno draw #" + target + ".\n" +
      "A Keno draw picks 20 unique numbers from 1..80. Bulls Eye is NOT in scope; ignore it.\n\n" +
      "Return ONLY this JSON:\n{\n  \"reasoning\": \"<short paragraph in-character reflecting your personality: " + AGENT_CONFIG[id].personality + ">\",\n" +
      "  \"notebook\": {\n    \"objective\": \"<one line>\",\n    \"hypothesis\": \"<one line for THIS round>\",\n    \"confidence\": <float 0..1>\n  },\n" +
      "  \"tickets\": [\n    {\"spots\": 5, \"numbers\": [n1..n5]},\n    {\"spots\": 6, \"numbers\": [n1..n6]},\n    {\"spots\": 7, \"numbers\": [n1..n7]},\n    {\"spots\": 8, \"numbers\": [n1..n8]}\n  ]\n}\n\n" +
      "Rules:\n- Numbers unique, in 1..80.\n- Tickets should NOT be trivial subsets/supersets.\n- Adapt to your own recent history; do not repeat the same method every round.\n- Speak in-character.\n\n" +
      "Recent official history (most recent first):\n" + historySummary(draws) + "\n\nYour private recent scoreboard:\n" + ownSummary(rounds, id) +
      "\n\nYour current lab status: " + statusLine(stats) + "\n";
  }
  function extractJson(text) {
    var m = /\{[\s\S]*\}/.exec(text || ""); if (!m) return null;
    try { return JSON.parse(m[0]); } catch (e) { return null; }
  }
  function validateTickets(payload) {
    var t = payload && payload.tickets; if (!Array.isArray(t)) return null;
    var valid = [], seen = {};
    t.forEach(function (x) {
      var spots = parseInt(x && x.spots, 10); var nums = (x && Array.isArray(x.numbers) ? x.numbers : []).map(function (n) { return parseInt(n, 10); });
      if ([5, 6, 7, 8].indexOf(spots) < 0 || nums.length !== spots) return;
      var u = {}; for (var i = 0; i < nums.length; i++) { if (!(nums[i] >= 1 && nums[i] <= 80) || u[nums[i]]) return; u[nums[i]] = 1; }
      if (seen[spots]) return; seen[spots] = 1;
      valid.push({ spots: spots, numbers: nums.sort(function (a, b) { return a - b; }) });
    });
    return valid.length >= 3 ? valid : null;
  }
  function hashStr(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; var t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function fallbackPrediction(id, seed) {
    var r = rng(hashStr(id + ":" + seed));
    var tickets = [5, 6, 7, 8].map(function (k) {
      var pool = []; for (var i = 1; i <= 80; i++) pool.push(i);
      for (var j = 0; j < k; j++) { var x = j + Math.floor(r() * (80 - j)); var tmp = pool[j]; pool[j] = pool[x]; pool[x] = tmp; }
      return { spots: k, numbers: pool.slice(0, k).sort(function (a, b) { return a - b; }) };
    });
    return { reasoning: "[" + id + "] fallback sample — LLM unreachable this round.", notebook: { objective: "survive round", hypothesis: "uniform sample", confidence: 0.1 }, tickets: tickets, fallback: true };
  }
  function judgeReleasePrompt(target, recentStats, consensus) {
    return "Deciding whether to release a Tennessee Keno prediction to the user for draw #" + target + ".\n\n" +
      "Recent verified performance (per AI):\n" + JSON.stringify(recentStats, null, 2) + "\n\n" +
      "Consensus among the three AIs for this round:\n" + JSON.stringify(consensus, null, 2) + "\n\n" +
      "Random baseline:\nRandom uniform baseline: for an 8-pick, expected hits ≈ 20·8/80 = 2.0.\n\n" +
      "Respond ONLY with JSON:\n{\"release\": true|false, \"source\":\"alpha\"|\"beta\"|\"gamma\"|\"consensus\"|\"none\", \"reasoning\":\"<one paragraph>\"}\n" +
      "Default to release=false unless evidence is unusually strong.";
  }
  function pressPrompt(dn, standings, events) {
    return "You are the Judge AI. After draw #" + dn + " (LIVE mode), publish a short press-room statement.\n\n" +
      "Current standings snapshot:\n" + JSON.stringify(standings, null, 2) + "\n\nNotable events this round:\n- " +
      (events.length ? "\n- " + events.join("\n- ") : "none") +
      "\n\nReturn ONLY JSON: {\"headline\":\"<8-12 words>\", \"body\":\"<2-3 sentence paragraph>\"}\nBe neutral, factual, cautious. Never claim a prediction will win.";
  }

  return {
    SOURCE_URL: SOURCE_URL, AGENT_CONFIG: AGENT_CONFIG, AI_IDS: AI_IDS, JUDGE_PERSONA: JUDGE_PERSONA,
    parseCTL: parseCTL, cleanDraws: cleanDraws, validDraw: validDraw,
    scoreTicket: scoreTicket, scorePrediction: scorePrediction, rankPredictions: rankPredictions,
    computeXp: computeXp, computeConsensus: computeConsensus, rankFor: rankFor,
    defaultStats: defaultStats, applyRoundResult: applyRoundResult, updateChampion: updateChampion,
    scoreRound: scoreRound, playerPrompt: playerPrompt, extractJson: extractJson,
    validateTickets: validateTickets, fallbackPrediction: fallbackPrediction,
    judgeReleasePrompt: judgeReleasePrompt, pressPrompt: pressPrompt
  };
});
