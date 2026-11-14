const $ = (s) => document.querySelector(s);
const money = (n) => n >= 1e6 ? "€" + (n / 1e6).toFixed(n >= 1e8 ? 0 : 1) + "m" : "€" + Math.round(n / 1000) + "k";
const escape = (s) => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let chosenModel = "valuation_aware";
let allPlayers = [], filtered = [], selected, metadata, limit = 40, selectionVersion = 0;
async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let body; try { body = await response.json(); } catch { body = {}; }
    const detail = Array.isArray(body.detail) ? body.detail.map(x => x.msg).join("; ") : body.detail;
    throw new Error(detail || "Could not load data. Please try again.");
  }
  return response.json();
}
function showError(error) { $("#error").textContent = error.message; $("#error").hidden = false; }
function switchTab(tab) {
  $("#desk").hidden = tab !== "desk"; $("#method").hidden = tab !== "method";
  document.querySelectorAll(".nav").forEach(n => n.classList.toggle("active", n.dataset.tab === tab));
}
document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
function renderList() {
  const normalize = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const query = normalize($("#search").value);
  filtered = allPlayers.filter(p => normalize(p.name + " " + p.club).includes(query)
    && (!$("#league").value || p.league === $("#league").value)
    && (!$("#position").value || p.position === $("#position").value));
  $("#player-count").textContent = filtered.length.toLocaleString() + " players in snapshot";
  $("#player-list").innerHTML = filtered.slice(0, limit).map(p =>
    '<button class="player ' + (selected?.player_id === p.player_id ? "selected" : "") + '" data-id="' + p.player_id + '"><span class="avatar">' +
    escape(p.name.split(" ").map(x => x[0]).slice(0, 2).join("")) + '</span><span><span class="name">' + escape(p.name) +
    '</span><span class="club">' + escape(p.club) + '</span></span><span class="price">' + money(p.actual_value) + "</span></button>"
  ).join("") || '<p class="empty">No matching players. Try another name or clear your filters.</p>';
  $("#show-more").hidden = filtered.length <= limit;
}
["search","league","position"].forEach(id => $("#" + id).addEventListener(id === "search" ? "input" : "change", () => { limit = 40; renderList(); }));
$("#show-more").addEventListener("click", () => { limit += 40; renderList(); });
$("#player-list").addEventListener("click", e => { const b = e.target.closest("[data-id]"); if (b) openPlayer(Number(b.dataset.id)); });
function chart(history) {
  if (history.length < 2) return '<p class="note">Not enough historical valuations to draw a trend.</p>';
  const dates = history.map(p => Date.parse(p.date));
  const values = history.map(p => p.market_value_in_eur);
  const max = Math.max(...values), minDate = Math.min(...dates), range = Math.max(...dates) - minDate || 1;
  const points = values.map((v,i) => [5 + (dates[i] - minDate) / range * 490, 125 - v / max * 110]);
  const line = points.map(p => p.join(",")).join(" ");
  return '<svg class="chart" viewBox="0 0 500 140" role="img" aria-label="Source market value history, maximum ' + escape(money(max)) +
    '"><line x1="0" y1="125" x2="500" y2="125" stroke="#d8ddd2"/><line x1="0" y1="65" x2="500" y2="65" stroke="#e9ece2" stroke-dasharray="4"/><polygon points="5,125 ' +
    line + ' 495,125" fill="#d7f36a" opacity=".22"/><polyline points="' + line +
    '" fill="none" stroke="#66843b" stroke-width="2.5"/><text x="5" y="12" fill="#78847c" font-size="9">' + money(max) +
    '</text></svg><div class="chart-years"><span>' + history[0].date.slice(0,4) + '</span><span>SYNTHETIC DEMO HISTORY</span><span>' + history.at(-1).date.slice(0,4) + '</span></div>';
}
async function openPlayer(id) {
  const version = ++selectionVersion;
  try {
    $("#error").hidden = true;
    const p = await api("/api/players/" + id);
    if (version !== selectionVersion) return;
    selected = p; renderList();
    $("#detail").innerHTML = '<article class="report"><div class="report-head"><div class="report-top"><p class="eyebrow">PLAYER REPORT / ' + p.player_id +
      '</p><span class="tag">' + escape(p.league_name) + '</span></div><h3>' + escape(p.name) +
      '</h3><p class="report-subtitle">' + escape(p.club) + ' · ' + escape(p.position) + ' · Age ' + p.age.toFixed(1) +
      ' at valuation</p></div><div class="value-block"></div><div class="report-body"><p class="section-label">PERFORMANCE INPUTS<span>365 days before valuation</span></p><div class="stats">' +
      [["Minutes",p.minutes.toLocaleString()],["Goals",p.goals],["Assists",p.assists],["Goals / 90",p.goals_per90.toFixed(2)]].map(([label,value]) => '<div class="stat"><span>' + label + '</span><b>' + value + '</b></div>').join("") +
      '</div><p class="section-label">VALUE OVER TIME<span>Fictional values, not recorded market prices</span></p>' + chart(p.history) +
      '<p class="section-label">SIMILAR PROFILES<span>Age, playing time & attacking output</span></p><div class="peers">' +
      p.peers.map(peer => '<button class="peer" data-peer="' + peer.player_id + '">' + escape(peer.name) + '<span>' +
      escape(peer.league_name) + ' · ' + money(peer.actual_value) + '</span></button>').join("") +
      '</div><p class="note">Comparisons use the latest available snapshot for each player; dates can differ. Stats last recorded ' + p.stats_through +
      '. Defensive and goalkeeper comparisons are limited by the available features.</p></div><div class="report-actions"><button class="primary" id="toggle-scenario">Try different stats ↗</button><a target="_blank" rel="noopener" href="https://www.transfermarkt.com/spieler/profil/spieler/' +
      p.player_id + '">Player source ↗</a></div><div class="scenario" id="scenario" hidden></div></article>';
    renderValues(p);
    if (metadata.synthetic_demo) {
      const sourceLink=$('#detail .report-actions a');
      if(sourceLink) sourceLink.remove();
    }
    document.querySelectorAll("[data-peer]").forEach(b => b.addEventListener("click", () => openPlayer(Number(b.dataset.peer))));
    $("#toggle-scenario").addEventListener("click", () => { $("#scenario").hidden = !$("#scenario").hidden; if (!$("#scenario").hidden) renderScenario(p); });
  } catch (error) { if (version === selectionVersion) showError(error); }
}
function renderValues(p) {
  const update = chosenModel === "valuation_aware";
  const fallback = p.valuation_aware_method === "stats_only_fallback";
  const value = update ? p.valuation_aware_value : p.predicted_value;
  const low = update ? p.valuation_aware_lower : p.lower;
  const high = update ? p.valuation_aware_upper : p.upper;
  $(".value-block").innerHTML = '<label class="model-choice">View estimate<select id="model-select" aria-label="Estimate model"><option value="valuation_aware">Valuation-aware update</option><option value="stats_only">Stats-only estimate</option></select></label>' +
    '<div class="value-label">' + (update ? 'VALUATION-AWARE UPDATE' : 'STATS-ONLY ESTIMATE') + ' · AS OF ' + p.date + '</div>' +
    '<div class="big-value">' + money(value) + '</div><div class="value-range">Illustrative, uncalibrated band: ' + money(low) + ' – ' + money(high) + '</div>' +
    '<p class="model-explanation">Synthetic demo only. ' + (update ? 'Previous-value baseline: retains the fictional previous value. No demo validation or improvement is claimed.' : 'Illustrative arithmetic rule, not a trained model or real-player appraisal.') + '</p>' +
    '<div class="comparison" aria-label="Model comparison"><div><span>Stats-only estimate</span><b>' + money(p.predicted_value) + '</b></div><div><span>Valuation-aware update</span><b>' + money(p.valuation_aware_value) + '</b></div><div><span>Recorded source value · ' + p.date + '</span><b>' + money(p.actual_value) + '</b></div></div>' +
    '<p class="value-range">Previous source valuation: ' + (p.previous_value == null ? 'unavailable' : money(p.previous_value) + ' on ' + p.previous_value_date + ' (' + p.previous_value_age_days + ' days earlier)') +
    '<br>Performance window: ' + beforeDate(p.date, 365) + ' to before ' + p.date +
    '<br>Latest included appearance: ' + p.stats_through + '. No live feed.</p>';
  $("#model-select").value = chosenModel;
  $("#model-select").addEventListener("change", e => {
    chosenModel = e.target.value; renderValues(p);
    if (!$("#scenario").hidden) renderScenario(p);
  });
}
function beforeDate(day, days) {
  const date = new Date(day + "T00:00:00Z"); date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}
function renderScenario(p) {
  const fields = [["age","Age",16,42,.01],["minutes","Minutes · 365 days",180,10000,1],["appearances","Appearances · 365 days",1,120,1],
    ["goals","Goals · 365 days",0,150,1],["assists","Assists · 365 days",0,150,1],["yellow_cards","Yellow cards",0,60,1],
    ["red_cards","Red cards",0,20,1],["recent_minutes","Minutes · last 90 days",0,4000,1],["recent_goals","Goals · last 90 days",0,80,1],
    ["recent_assists","Assists · last 90 days",0,80,1]];
  $("#scenario").innerHTML = '<h4>Explore a scenario</h4><p class="note">Selected mode: ' + (chosenModel === 'valuation_aware' ? 'valuation-aware update. The selected previous-value baseline ignores performance edits when a prior price is present.' : 'stats-only estimate.') +
    ' Inputs are supplied by you, not fetched or verified. Keep 90-day totals within annual totals. Dates must describe the same rolling windows. Clear both prior-price fields to try the stats-only fallback.</p><form id="scenario-form"><div class="form-grid">' +
    fields.map(([key,label,min,max,step]) => '<label>' + label + '<input required type="number" name="' + key + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + p[key] + '"></label>').join('') +
    '<label>Estimate as of<input required type="date" name="stats_as_of" max="' + new Date().toISOString().slice(0,10) + '" value="' + p.date + '"></label>' +
    '<label>Performance through<input type="date" name="stats_through" value="' + p.stats_through + '"></label>' +
    '<label>Previous valuation (€)<input type="number" name="previous_value" min="1" max="10000000000" step="1" value="' + (p.previous_value ?? '') + '"></label>' +
    '<label>Previous valuation date<input type="date" name="previous_value_date" value="' + (p.previous_value_date ?? '') + '"></label>' +
    '</div><button class="primary" type="submit">Calculate scenario</button></form><div id="scenario-result" class="scenario-result" role="status"></div>';
  $("#scenario-form").addEventListener("submit", async e => {
    e.preventDefault();
    const button = e.target.querySelector('button'), output = $("#scenario-result");
    button.disabled = true; output.textContent = 'Calculating…';
    const payload = Object.fromEntries(new FormData(e.target));
    fields.forEach(([key]) => payload[key] = Number(payload[key]));
    payload.previous_value = payload.previous_value === '' ? null : Number(payload.previous_value);
    payload.previous_value_date ||= null; payload.stats_through ||= null;
    payload.position = p.position; payload.league = p.league; payload.model = chosenModel;
    try {
      const result = await api('/api/predict', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if (!output.isConnected) return;
      output.innerHTML = '<strong>' + money(result.predicted_value) + '</strong><br>Method: ' + escape(result.method.replaceAll('_',' ')) +
        '<br>Illustrative, uncalibrated band: ' + money(result.lower) + ' – ' + money(result.upper) + '<br>' +
        result.sensitivities.map(x => escape(x.label) + ': ' + (x.difference_eur >= 0 ? '+' : '−') + money(Math.abs(x.difference_eur))).join('<br>') +
        '<p class="note">These changes describe model behavior, not causal effects. ' + escape(result.warning) + '</p>';
    } catch (error) { if (output.isConnected) output.textContent = error.message; }
    finally { button.disabled = false; }
  });
}
function renderMethod(m) {
  $('#method-content').innerHTML='<article class="method-card"><h3>Synthetic demo ? no production evaluation</h3>' +
    '<p>All 12 players, clubs, statistics, prices and dates are fictional fixtures. No real provider data or serialized models are loaded.</p>' +
    '<p>The previous-value baseline retains the supplied earlier value. The stats-only view uses an illustrative arithmetic rule, not a trained estimator. Bands are not calibrated confidence intervals.</p>' +
    '<p>Earlier private research selected the previous-value baseline; the PitchAPI pilot did not establish a better production model. Its exports and learned models are withheld pending redistribution-rights verification.</p>' +
    '<p>No live feed, API key or external account is required. This build demonstrates search, reports, comparisons and validated scenarios, not real scouting values.</p></article>';
}
async function init() {
  try {
    [metadata, allPlayers] = await Promise.all([api("/api/metadata"), api("/api/players")]);
    $("#source-status").textContent = "SYNTHETIC DEMO — fictional players and values · Fixture dates " + metadata.source.appearances_through +
      " / " + metadata.source.valuations_through + " · Not real historical or live data";
    renderMethod(metadata); renderList();
    if (allPlayers.length) await openPlayer(allPlayers[0].player_id);
  } catch (error) { showError(error); $("#source-status").textContent = "Data unavailable — check the message below."; }
}
init();
