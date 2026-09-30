/* Pokéradar – Dashboard */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const S = {
    radar: { produkte: [], deals: [], marktnews: [], konfig: {} },
    market: { produkte: [], tage: 0, stand: null },
    status: {},
    f: { sprache: new Set(["de", "en"]), typ: new Set(["etb", "display", "upc"]) },
    tab: "radar",
    sort: "ch7", q: "", limit: 40,
  };

  const TYP = { etb: "Elite-Trainer-Box", display: "Display", upc: "Ultra-Premium-Kollektion" };
  const TYP_KURZ = { etb: "ETB", display: "Display", upc: "UPC" };
  const LANG = { de: "DE", en: "EN", jp: "JP", int: "DE/EN" };
  const STAGE = {
    vorbestellbar: ["Jetzt vorbestellbar", "live"], nachschub: ["Nachschub", "restock"],
    angekuendigt: ["Angekündigt", "ann"], ausverkauft: ["Ausverkauft", "sold"], erschienen: ["Erschienen", ""],
  };
  const PRIO = { vorbestellbar: 0, nachschub: 1, angekuendigt: 2, ausverkauft: 3, erschienen: 4 };
  const HERO = {
    radar: ["Nichts Limitiertes<br>mehr verpassen.", "Elite-Trainer-Boxen, Displays und Ultra-Premium-Kollektionen – vom ersten Gerücht bis zum Vorverkauf."],
    deals: ["Schnäppchen,<br>die sich lohnen.", "Jedes Angebot gegen den Cardmarket-Trend gerechnet – mit Rating, Begründung und Lieferwelle."],
    markt: ["Der Markt<br>im Blick.", "Was steigt, was fällt – täglich aus der Cardmarket-Preisübersicht."],
    kalender: ["Wann es<br>losgeht.", "Vorverkaufsstarts und Releases, sobald sie irgendwo auftauchen."],
  };

  // ── Formatierung ───────────────────────────────────────────
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const url = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
  const nf0 = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
  const eur = (x, genau) => (x == null ? "–" : (genau || x < 100 ? nf2 : nf0).format(x));
  const orig = (p, w) => (w === "USD" ? `$${p.toFixed(2)}` : w === "JPY" ? `¥${Math.round(p).toLocaleString("de-DE")}` : null);
  const pct = (x) => (x == null ? "–" : `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toLocaleString("de-DE", { maximumFractionDigits: Math.abs(x) < 10 ? 1 : 0 })} %`);
  const dir = (x) => (x == null || Math.abs(x) < 1 ? "flat" : x > 0 ? "up" : "down");
  const d = (s) => (s ? new Date(s.length <= 10 ? s + "T12:00:00" : s) : null);
  const datum = (s, opt = { day: "2-digit", month: "2-digit", year: "numeric" }) => (s ? d(s).toLocaleDateString("de-DE", opt) : "–");
  const kurzDatum = (s) => datum(s, { day: "numeric", month: "short" });
  function rel(s) {
    if (!s) return "";
    const min = Math.round((Date.now() - d(s)) / 60000);
    if (min < 1) return "gerade eben";
    if (min < 60) return `vor ${min} Min.`;
    const h = Math.round(min / 60);
    if (h < 24) return `vor ${h} Std.`;
    const t = Math.round(h / 24);
    return t === 1 ? "gestern" : t < 7 ? `vor ${t} Tagen` : kurzDatum(s);
  }

  // ── Filter ─────────────────────────────────────────────────
  const zeigSprache = (sp) => (sp === "int" ? S.f.sprache.has("de") || S.f.sprache.has("en") : S.f.sprache.has(sp));
  const passt = (x) => S.f.typ.has(x.typ) && zeigSprache(x.sprache);

  // ── Bausteine ──────────────────────────────────────────────
  function boxSvg(typ) {
    if (typ === "display") {
      return `<svg class="box" viewBox="0 0 130 120" aria-hidden="true">
        ${[0, 1, 2, 3, 4].map((i) => `<rect x="${22 + i * 15}" y="${18 + (i % 2) * 7 + (i === 2 ? -6 : 0)}" width="17" height="44" rx="3"
            fill="url(#pk-${typ})" stroke="#fff" stroke-width="1.6" transform="rotate(${(i - 2) * 3} ${30 + i * 15} 60)"/>`).join("")}
        <defs><linearGradient id="pk-${typ}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#ffe7b0"/></linearGradient></defs>
        <polygon points="12,52 92,62 92,114 12,102" fill="#fff" opacity=".97"/>
        <polygon points="92,62 120,50 120,100 92,114" fill="#fff" opacity=".72"/>
        <polygon points="12,52 40,42 120,50 92,62" fill="#000" opacity=".12"/>
        <rect x="26" y="74" width="50" height="7" rx="3.5" fill="var(--b)" opacity=".85" transform="skewY(7)"/>
        <rect x="26" y="86" width="32" height="5" rx="2.5" fill="var(--a)" opacity=".7" transform="skewY(7)"/>
      </svg>`;
    }
    if (typ === "upc") {
      return `<svg class="box" viewBox="0 0 130 120" aria-hidden="true">
        <polygon points="8,40 88,52 88,112 8,100" fill="#15122e"/>
        <polygon points="88,52 122,38 122,96 88,112" fill="#0d0b1f"/>
        <polygon points="8,40 44,27 122,38 88,52" fill="#2a2360"/>
        <polyline points="8,40 88,52 122,38" fill="none" stroke="var(--gold)" stroke-width="2"/>
        <polyline points="88,52 88,112" fill="none" stroke="var(--gold)" stroke-width="1.4" opacity=".8"/>
        <polygon points="8,100 88,112 88,106 8,94" fill="var(--gold)" opacity=".55"/>
        <g transform="translate(48 80) skewY(8)">
          <path d="M0-18 5-6 18-5 8 3 11 16 0 9-11 16-8 3-18-5-5-6z" fill="var(--gold)"/>
          <circle r="4" fill="#15122e"/>
        </g>
      </svg>`;
    }
    return `<svg class="box" viewBox="0 0 130 120" aria-hidden="true">
      <polygon points="10,42 88,54 88,112 10,100" fill="#fff" opacity=".97"/>
      <polygon points="88,54 120,42 120,98 88,112" fill="#fff" opacity=".7"/>
      <polygon points="10,42 42,30 120,42 88,54" fill="#fff"/>
      <polygon points="10,42 88,54 88,64 10,52" fill="#000" opacity=".08"/>
      <g transform="translate(49 83) skewY(8)">
        <circle r="13" fill="#fff" stroke="#1d1d1f" stroke-width="2.6"/>
        <path d="M-13 0a13 13 0 0 1 26 0z" fill="var(--a)"/>
        <path d="M-13 0h26" stroke="#1d1d1f" stroke-width="2.6"/>
        <circle r="4.2" fill="#fff" stroke="#1d1d1f" stroke-width="2.4"/>
      </g>
    </svg>`;
  }

  const setName = (x) => x.set || (x.name || x.produkt || "").replace(/(pok[eé]mon center|elite trainer box|booster box|ultra-premium collection|display|top-trainer-box|\(18 boosters\))/gi, "").trim() || TYP[x.typ];

  function art(x, { lang = true, text = true, holo = false } = {}) {
    return `<div class="art ${esc(x.typ)}">
      <div class="ghost"></div>
      ${lang ? `<span class="lang">${esc(LANG[x.sprache] || "")}</span>` : ""}
      ${text ? `<div class="set"><small>${esc(TYP_KURZ[x.typ] || "")}</small>${esc(setName(x))}</div>` : ""}
      ${boxSvg(x.typ)}
      ${holo ? `<div class="holo"></div>` : ""}
    </div>`;
  }

  function balls(r, big) {
    if (!r) return "";
    const n = r.sterne || 0;
    return `<span class="rating${big ? " big" : ""}" title="Radar-Rating ${n}/5 · ${esc(r.urteil)}" aria-label="Radar-Rating ${n} von 5">
      ${[1, 2, 3, 4, 5].map((i) => `<svg class="${i <= n ? "on" : ""}"><use href="#ball"/></svg>`).join("")}
      ${big ? `<span class="lbl">${esc(r.urteil)}</span>` : ""}</span>`;
  }

  const why = (gr) => (gr && gr.length ? `<ul class="why">${gr.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>` : "");
  const stagePill = (s) => (STAGE[s] ? `<span class="pill ${STAGE[s][1]}">${STAGE[s][0]}</span>` : "");
  const wellePill = (x) => (x.lieferwelle ? `<span class="pill wave">Welle ${x.lieferwelle}${x.liefertermin ? " · " + esc(x.liefertermin) : ""}</span>`
    : x.liefertermin ? `<span class="pill wave">Lieferung ${esc(x.liefertermin)}</span>` : "");

  function spark(werte, cls = "spark", w = 104, h = 30) {
    const v = (werte || []).filter((x) => x != null);
    if (v.length < 2) return `<svg class="${cls} flat" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="wait" d="M2 ${h / 2}H${w - 2}"/></svg>`;
    const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
    const pts = v.map((y, i) => [2 + (i * (w - 4)) / (v.length - 1), h - 3 - ((y - lo) / sp) * (h - 6)]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
    const fill = `${line}L${w - 2} ${h}L2 ${h}Z`;
    const k = dir(((v[v.length - 1] / v[0]) - 1) * 100);
    return `<svg class="${cls} ${k}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="f" d="${fill}"/><path class="l" d="${line}"/></svg>`;
  }

  const chg = (x, cls = "") => `<span class="chg ${dir(x)} ${cls}">${x == null ? "–" : pct(x)}</span>`;
  const leer = (titel, text) => `<div class="empty"><img class="e-ic" src="favicon.svg" alt=""><b>${titel}</b>${text}</div>`;

  // ── Radar ──────────────────────────────────────────────────
  function produktKarte(p, gross) {
    const foil = (p.rating?.sterne || 0) >= 4;
    const termine = [
      p.vorverkauf_ab ? `<span class="pill">VVK ${kurzDatum(p.vorverkauf_ab)}</span>` : "",
      p.erscheint_am ? `<span class="pill">Release ${kurzDatum(p.erscheint_am)}</span>` : "",
    ].join("");
    return `<button class="card${foil ? " foil" : ""}" data-p="${esc(p.key)}">
      ${art(p, { holo: foil })}
      <div class="body">
        <div class="row"><span class="title">${esc(p.name)}</span></div>
        <div class="row">${balls(p.rating)}<span class="hype">Hype ${p.hype}/10</span></div>
        ${gross ? why(p.rating?.gruende?.slice(0, 3)) : `<div class="kurz">${esc(p.kurz || "")}</div>`}
        <div class="meta">${stagePill(p.stage)}${termine}${wellePill(p)}
          ${p.preis_eur ? `<span class="pill">${eur(p.preis_eur, true)}</span>` : ""}
          <span class="pill">${rel(p.aktualisiert || p.erstmals)}</span></div>
      </div>
    </button>`;
  }

  function renderRadar() {
    const alle = S.radar.produkte.filter(passt);
    const deals = S.radar.deals.filter(passt);
    const jetzt = alle.filter((p) => p.stage === "vorbestellbar" || p.stage === "nachschub");
    const woche = alle.filter((p) => Date.now() - d(p.erstmals) < 7 * 864e5);
    const bester = deals.filter((x) => x.rabatt > 0).sort((a, b) => b.rabatt - a.rabatt)[0];
    $("#tiles").innerHTML = `
      <div class="tile"><div class="k">Jetzt vorbestellbar</div><div class="v ${jetzt.length ? "up" : ""}">${jetzt.length}</div>
        <div class="s">${jetzt[0] ? esc(jetzt[0].name) : "Gerade nichts offen"}</div></div>
      <div class="tile"><div class="k">Neu in 7 Tagen</div><div class="v">${woche.length}</div>
        <div class="s">${alle.length} Boxen insgesamt auf dem Radar</div></div>
      <div class="tile clickable" data-goto="deals"><div class="k">Bestes Schnäppchen</div>
        <div class="v ${bester ? "up" : ""}">${bester ? "−" + Math.round(bester.rabatt) + " %" : "–"}</div>
        <div class="s">${bester ? esc(bester.produkt) : "Noch kein Angebot unter Marktpreis"}</div></div>`;

    const hot = alle.filter((p) => jetzt.includes(p) || (p.rating?.sterne || 0) >= 5)
      .sort((a, b) => (PRIO[a.stage] - PRIO[b.stage]) || (b.rating?.sterne - a.rating?.sterne) || (b.hype - a.hype)).slice(0, 3);
    $("#radar-hot").innerHTML = hot.length ? `<div class="head"><h2>Jetzt zuschlagen</h2><span class="muted">Offene Vorverkäufe und Top-Ratings</span></div>
      <div class="grid hot">${hot.map((p) => produktKarte(p, true)).join("")}</div>` : "";

    const rest = alle.filter((p) => !hot.includes(p))
      .sort((a, b) => (PRIO[a.stage] ?? 9) - (PRIO[b.stage] ?? 9) || (d(b.aktualisiert || b.erstmals) - d(a.aktualisiert || a.erstmals)));
    $("#radar-count").textContent = alle.length ? `${alle.length} ${alle.length === 1 ? "Box" : "Boxen"}` : "";
    $("#view-radar > .head").hidden = !rest.length && hot.length > 0;
    $("#radar-grid").innerHTML = rest.length ? rest.map((p) => produktKarte(p)).join("")
      : hot.length ? "" : leer("Noch ruhig auf dem Radar", "<br>Sobald eine passende Box auftaucht, erscheint sie hier – und auf deinem Handy.");
  }

  // ── Schnäppchen ────────────────────────────────────────────
  function dealKarte(x) {
    const o = x.waehrung && x.waehrung !== "EUR" && x.preis ? orig(x.preis, x.waehrung) : null;
    return `<button class="deal" data-d="${esc(x.id)}">
      <div class="mini">${art(x, { text: false, lang: false })}${x.rabatt > 0 ? `<span class="off">−${Math.round(x.rabatt)} %</span>` : ""}</div>
      <div class="body" style="padding:0">
        <span class="title">${esc(x.produkt)}</span>
        <div class="price"><span class="now">${x.preis_eur ? eur(x.preis_eur, true) : "Preis ?"}</span>
          ${x.markt?.trend ? `<span class="was">${eur(x.markt.trend, true)}</span>` : ""}
          ${o ? `<span class="src">${o}</span>` : ""}</div>
        ${balls(x.rating, true)}
        ${why(x.rating?.gruende?.slice(0, 3))}
        <div class="meta">${x.haendler ? `<span class="pill">${esc(x.haendler)}</span>` : ""}${wellePill(x)}
          <span class="pill">${esc(LANG[x.sprache])}</span><span class="pill">${esc(x.quelle)} · ${rel(x.datum)}</span></div>
      </div>
    </button>`;
  }

  function renderDeals() {
    const liste = S.radar.deals.filter(passt)
      .sort((a, b) => (b.rating?.sterne - a.rating?.sterne) || (d(b.datum) - d(a.datum)));
    $("#deals").innerHTML = liste.length ? liste.map(dealKarte).join("")
      : leer("Gerade keine Angebote", "<br>Das Radar prüft mydealz, Reddit und die News alle 20 Minuten.");
  }

  // ── Markt ──────────────────────────────────────────────────
  function mrow(e, kompakt) {
    return `<button class="mrow" data-m="${e.id}">
      <span class="sw">${art(e, { text: false, lang: false })}</span>
      <span class="nm"><b>${esc(e.name)}</b><span>${esc(LANG[e.sprache])} · ${esc(TYP_KURZ[e.typ])}${e.low ? ` · ab ${eur(e.low)}` : ""}</span></span>
      ${kompakt ? "" : spark(e.spark)}
      <span class="pr">${eur(e.trend)}${kompakt ? "" : `<small>Trend</small>`}</span>
      ${chg(e.ch7)}
      ${kompakt ? "" : chg(e.ch30, "c30")}
    </button>`;
  }

  function renderMarkt() {
    const m = S.market;
    const alle = m.produkte.filter(passt);
    const tage = m.tage || 0;
    if (tage < 8) {
      const pr = Math.min(1, tage / 8), U = 2 * Math.PI * 26;
      const ab7 = new Date(d(m.stand || new Date().toISOString().slice(0, 10)).getTime() + (8 - tage) * 864e5);
      $("#markt-intro").innerHTML = `<div class="build">
        <svg class="ring" viewBox="0 0 64 64"><circle class="t" cx="32" cy="32" r="26"/>
          <circle class="p" cx="32" cy="32" r="26" stroke-dasharray="${U}" stroke-dashoffset="${U * (1 - pr)}"/>
          <text x="32" y="33">${tage}/8</text></svg>
        <div><h3>Der Preisverlauf wird aufgebaut</h3>
          <p>Cardmarket liefert für versiegelte Produkte nur den Tagespreis – das Radar merkt sich jeden Tag einen Schnappschuss.
          Ab etwa ${datum(ab7.toISOString(), { day: "numeric", month: "long" })} siehst du hier 7-Tage-Bewegungen, nach einem Monat auch 30-Tage-Trends.
          Die aktuellen Preise sind schon jetzt da.</p></div></div>`;
    } else $("#markt-intro").innerHTML = "";

    const mitCh = alle.filter((e) => e.ch7 != null);
    let links, rechts;
    if (mitCh.length >= 6) {
      const up = [...mitCh].sort((a, b) => b.ch7 - a.ch7).filter((e) => e.ch7 > 0).slice(0, 6);
      const dn = [...mitCh].sort((a, b) => a.ch7 - b.ch7).filter((e) => e.ch7 < 0).slice(0, 6);
      links = ["↑", "up", "Steigt gerade", up];
      rechts = ["↓", "down", "Fällt gerade", dn];
    } else {
      links = ["★", "up", "Die wertvollsten Boxen", [...alle].sort((a, b) => b.trend - a.trend).slice(0, 6)];
      rechts = ["✦", "news", "Neu gelistet", [...alle].sort((a, b) => (b.seit || "").localeCompare(a.seit || "")).slice(0, 6)];
    }
    $("#movers").innerHTML = [links, rechts].map(([ic, c, t, l]) => `<div class="panel"><h3><span class="ic ${c}">${ic}</span>${t}</h3>
      ${l.length ? l.map((e) => mrow(e, true)).join("") : `<p class="muted" style="margin:6px 14px 12px">Keine deutlichen Bewegungen.</p>`}</div>`).join("");

    const news = S.radar.marktnews.filter((x) => zeigSprache(x.sprache)).slice(0, 6);
    $("#markt-news").innerHTML = news.length ? `<div class="panel" style="margin-top:16px"><h3><span class="ic news">❝</span>Aus den News</h3><div class="nlist">
      ${news.map((x) => `<a class="nitem" href="${url(x.link)}" target="_blank" rel="noopener"><b>${esc(x.titel)}</b>
        <span>${esc(x.quelle)} · ${rel(x.datum)}${x.trend ? " · " + (x.trend === "steigt" ? "↑ steigt" : "↓ fällt") : ""}</span></a>`).join("")}</div></div>` : "";

    const q = S.q.trim().toLowerCase();
    const key = S.sort;
    const liste = alle.filter((e) => !q || e.name.toLowerCase().includes(q))
      .sort((a, b) => key === "seit" ? (b.seit || "").localeCompare(a.seit || "")
        : key === "trend" ? b.trend - a.trend
        : (Math.abs(b[key] ?? -1) - Math.abs(a[key] ?? -1)) || b.trend - a.trend);
    $("#markt-liste").innerHTML = liste.length ? liste.slice(0, S.limit).map((e) => mrow(e)).join("")
      : `<p class="muted" style="padding:18px">Keine Box gefunden.</p>`;
    $("#markt-mehr").hidden = liste.length <= S.limit;
  }

  // ── Kalender ───────────────────────────────────────────────
  function renderKalender() {
    const grenze = new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10);
    const ev = [];
    for (const p of S.radar.produkte.filter(passt)) {
      if (p.vorverkauf_ab >= grenze) ev.push({ t: p.vorverkauf_ab, art: "Vorverkauf", p });
      if (p.erscheint_am >= grenze) ev.push({ t: p.erscheint_am, art: "Release", p });
    }
    ev.sort((a, b) => a.t.localeCompare(b.t));
    if (!ev.length) {
      $("#kalender").innerHTML = leer("Noch keine Termine", "<br>Sobald ein Vorverkaufs- oder Release-Datum gemeldet wird, steht es hier.");
      return;
    }
    const monate = {};
    for (const e of ev) (monate[e.t.slice(0, 7)] ||= []).push(e);
    $("#kalender").innerHTML = Object.entries(monate).map(([mo, l]) => `<div class="month">
      <h3>${d(mo + "-15").toLocaleDateString("de-DE", { month: "long", year: "numeric" })}</h3>
      <div class="list">${l.map((e) => `<button class="ev" data-p="${esc(e.p.key)}">
        <span class="day"><span>${d(e.t).toLocaleDateString("de-DE", { weekday: "short" })}</span><b>${d(e.t).getDate()}</b></span>
        <span class="t"><b>${esc(e.p.name)}</b><span>${e.art} · ${esc(LANG[e.p.sprache])} · ${esc(TYP[e.p.typ])}</span></span>
        ${balls(e.p.rating)}</button>`).join("")}</div></div>`).join("");
  }

  // ── Detail-Sheet ───────────────────────────────────────────
  const fact = (k, v) => (v == null || v === false || v === "" || v === "–" ? "" : `<div class="fact"><span>${k}</span><b>${v}</b></div>`);
  const cmLink = (name) => `https://www.cardmarket.com/de/Pokemon/Products/Search?searchString=${encodeURIComponent(name)}`;

  function sheet(html) {
    $("#sheet-body").innerHTML = html;
    $("#sheet").hidden = false;
    document.body.style.overflow = "hidden";
    $(".sheet").scrollTop = 0;
    $(".sheet .close").focus();
  }
  function sheetZu() {
    $("#sheet").hidden = true;
    document.body.style.overflow = "";
  }

  function sheetProdukt(p) {
    const m = p.markt;
    sheet(`<div class="card foil" style="border-radius:0;box-shadow:none;transform:none">${art(p, { holo: true })}</div>
      <div class="inner">
        <div><div class="meta" style="margin-bottom:10px">${stagePill(p.stage)}<span class="pill">${esc(LANG[p.sprache])}</span><span class="pill">${esc(TYP[p.typ])}</span></div>
          <h2 id="sheet-title">${esc(p.name)}</h2><p class="muted" style="margin:6px 0 0">${esc(p.kurz || "")}</p></div>
        <div class="box-why"><p class="label">Radar-Rating</p>${balls(p.rating, true)}${why(p.rating?.gruende)}</div>
        <div class="facts">
          ${fact("Vorverkauf ab", p.vorverkauf_ab && datum(p.vorverkauf_ab))}
          ${fact("Release", p.erscheint_am && datum(p.erscheint_am))}
          ${fact("Preis", p.preis_eur && eur(p.preis_eur, true))}
          ${fact("Lieferwelle", p.lieferwelle && `Welle ${p.lieferwelle}`)}
          ${fact("Lieferung", p.liefertermin && esc(p.liefertermin))}
          ${fact("Händler", p.haendler && esc(p.haendler))}
          ${fact("Hype", `${p.hype}/10`)}
          ${fact("Cardmarket-Trend", m?.trend && eur(m.trend, true))}
          ${fact("7 Tage", m?.ch7 != null && pct(m.ch7))}
        </div>
        <div><p class="label">Meldungen</p><div class="srcs">${(p.quellen || []).map((q) => `<a href="${url(q.link)}" target="_blank" rel="noopener">
          <b style="font-weight:500">${esc(q.titel)}</b><span>${esc(q.quelle)} · ${rel(q.datum)}</span></a>`).join("")}</div></div>
        <div class="cta">${p.quellen?.[0] ? `<a class="btn" href="${url(p.quellen[0].link)}" target="_blank" rel="noopener">Zur Meldung ↗</a>` : ""}
          ${m ? `<a class="btn alt" href="${cmLink(m.name)}" target="_blank" rel="noopener">Auf Cardmarket ↗</a>` : ""}</div>
      </div>`);
    holoFolgen($(".sheet .card"));
  }

  function sheetDeal(x) {
    const m = x.markt;
    const o = x.waehrung && x.waehrung !== "EUR" && x.preis ? orig(x.preis, x.waehrung) : null;
    sheet(`${art(x)}
      <div class="inner">
        <div><div class="meta" style="margin-bottom:10px">${x.rabatt > 0 ? `<span class="pill live">−${Math.round(x.rabatt)} % unter Markt</span>` : ""}${wellePill(x)}</div>
          <h2 id="sheet-title">${esc(x.produkt)}</h2><p class="muted" style="margin:6px 0 0">${esc(x.titel)}</p></div>
        <div class="box-why"><p class="label">Lohnt sich das?</p>${balls(x.rating, true)}${why(x.rating?.gruende)}</div>
        <div class="facts">
          ${fact("Angebot", x.preis_eur && eur(x.preis_eur, true) + (o ? ` <small class="muted">(${o})</small>` : ""))}
          ${fact("Cardmarket-Trend", m?.trend && eur(m.trend, true))}
          ${fact("Günstigstes auf CM", m?.low && eur(m.low, true))}
          ${fact("Händler", x.haendler && esc(x.haendler))}
          ${fact("Lieferwelle", x.lieferwelle && `Welle ${x.lieferwelle}`)}
          ${fact("Lieferung", x.liefertermin && esc(x.liefertermin))}
          ${fact("Markt 30 Tage", m?.ch30 != null && pct(m.ch30))}
          ${fact("Gefunden", `${esc(x.quelle)} · ${rel(x.datum)}`)}
        </div>
        ${m ? `<p class="muted" style="margin:0">Verglichen mit: ${esc(m.name)}</p>` : ""}
        <div class="cta"><a class="btn" href="${url(x.link)}" target="_blank" rel="noopener">Zum Angebot ↗</a>
          ${m ? `<a class="btn alt" href="${cmLink(m.name)}" target="_blank" rel="noopener">Auf Cardmarket ↗</a>` : ""}</div>
      </div>`);
  }

  function sheetMarkt(e) {
    sheet(`${art(e)}
      <div class="inner">
        <div><div class="meta" style="margin-bottom:10px"><span class="pill">${esc(LANG[e.sprache])}</span><span class="pill">${esc(TYP[e.typ])}</span></div>
          <h2 id="sheet-title">${esc(e.name)}</h2></div>
        <div>${spark(e.spark, "spark bigspark", 560, 90)}
          <p class="muted" style="margin:6px 0 0">${(e.spark || []).length > 1 ? `Trendpreis der letzten ${(e.spark || []).length} Tage` : "Verlauf startet – ab morgen gibt es die erste Linie."}</p></div>
        <div class="facts">
          ${fact("Trendpreis", eur(e.trend, true))}
          ${fact("Günstigstes Angebot", e.low && eur(e.low, true))}
          ${fact("7 Tage", e.ch7 != null && pct(e.ch7))}
          ${fact("30 Tage", e.ch30 != null && pct(e.ch30))}
          ${fact("90 Tage", e.ch90 != null && pct(e.ch90))}
          ${fact("Höchster Trend", e.hoch && eur(e.hoch, true))}
          ${fact("Auf Cardmarket seit", e.seit && datum(e.seit))}
        </div>
        ${e.rating ? `<div class="box-why"><p class="label">Radar-Rating</p>${balls(e.rating, true)}${why(e.rating.gruende)}</div>` : ""}
        <div class="cta"><a class="btn" href="${cmLink(e.name)}" target="_blank" rel="noopener">Auf Cardmarket ansehen ↗</a></div>
      </div>`);
  }

  // ── Holo-Effekt ────────────────────────────────────────────
  function holoFolgen(el) {
    if (!el) return;
    el.addEventListener("pointermove", (ev) => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${((ev.clientX - r.left) / r.width) * 100}%`);
      el.style.setProperty("--my", `${((ev.clientY - r.top) / r.height) * 100}%`);
    });
  }
  document.addEventListener("pointermove", (ev) => {
    const c = ev.target.closest?.(".card.foil");
    if (!c) return;
    const r = c.getBoundingClientRect();
    c.style.setProperty("--mx", `${((ev.clientX - r.left) / r.width) * 100}%`);
    c.style.setProperty("--my", `${((ev.clientY - r.top) / r.height) * 100}%`);
  }, { passive: true });

  // ── Steuerung ──────────────────────────────────────────────
  function render() {
    const [h, s] = HERO[S.tab];
    $("#hero-title").innerHTML = h;
    $("#hero-sub").textContent = s;
    for (const t of Object.keys(HERO)) $(`#view-${t}`).hidden = t !== S.tab;
    $$(".bar .seg button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === S.tab)));
    $$("#f-sprache button").forEach((b) => b.setAttribute("aria-pressed", String(S.f.sprache.has(b.dataset.v))));
    $$("#f-typ button").forEach((b) => b.setAttribute("aria-pressed", String(S.f.typ.has(b.dataset.v))));
    ({ radar: renderRadar, deals: renderDeals, markt: renderMarkt, kalender: renderKalender })[S.tab]();
  }

  function tab(t, push = true) {
    if (!HERO[t]) t = "radar";
    S.tab = t;
    if (push && location.hash !== "#" + t) history.replaceState(null, "", "#" + t);
    render();
  }

  function filterSpeichern() {
    localStorage.setItem("pokeradar.filter", JSON.stringify({ sprache: [...S.f.sprache], typ: [...S.f.typ] }));
  }

  function umschalten(set, v) {
    if (set.has(v)) { if (set.size > 1) set.delete(v); } else set.add(v);
    filterSpeichern();
    render();
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target;
    const b = t.closest("button, [data-goto], [data-close]");
    if (!b) return;
    if (b.matches("[data-close]")) return sheetZu();
    if (b.dataset.tab) return tab(b.dataset.tab);
    if (b.dataset.goto) return tab(b.dataset.goto);
    if (b.closest("#f-sprache")) return umschalten(S.f.sprache, b.dataset.v);
    if (b.closest("#f-typ")) return umschalten(S.f.typ, b.dataset.v);
    if (b.closest("#markt-sort")) {
      S.sort = b.dataset.v; S.limit = 40;
      $$("#markt-sort button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      return renderMarkt();
    }
    if (b.id === "markt-mehr") { S.limit += 60; return renderMarkt(); }
    if (b.dataset.p) { const p = S.radar.produkte.find((x) => x.key === b.dataset.p); if (p) sheetProdukt(p); return; }
    if (b.dataset.d) { const x = S.radar.deals.find((y) => y.id === b.dataset.d); if (x) sheetDeal(x); return; }
    if (b.dataset.m) { const e = S.market.produkte.find((y) => String(y.id) === b.dataset.m); if (e) sheetMarkt(e); }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("#sheet").hidden) sheetZu(); });
  $("#markt-suche").addEventListener("input", (ev) => { S.q = ev.target.value; S.limit = 40; renderMarkt(); });
  window.addEventListener("hashchange", () => tab(location.hash.slice(1), false));

  function live() {
    const st = S.status;
    const el = $("#live");
    if (!st.lauf) { $("#live-text").textContent = "Noch kein Lauf"; el.classList.add("stale"); return; }
    const alt = Date.now() - d(st.lauf) > 90 * 60000;
    el.classList.toggle("stale", alt);
    $("#live-text").textContent = `${alt ? "Zuletzt" : "Live"} · ${rel(st.lauf)}`;
    const q = Object.entries(st.quellen || {}).map(([k, v]) => `${v === "ok" ? "✓" : "✗"} ${k}`).join("\n");
    el.title = `Letzter Lauf: ${d(st.lauf).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}\nKI: ${st.modell || (st.ki ? "aktiv" : "Regeln")}\nMarkt-Stand: ${st.markt_stand || "–"}\n\n${q}`;
  }

  async function laden() {
    const get = (f) => fetch(`data/${f}?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [radar, market, status] = await Promise.all([get("radar.json"), get("market.json"), get("status.json")]);
    if (radar) S.radar = { produkte: [], deals: [], marktnews: [], ...radar };
    if (market) S.market = { produkte: [], tage: 0, ...market };
    if (status) S.status = status;
    const gespeichert = JSON.parse(localStorage.getItem("pokeradar.filter") || "null");
    const quelle = gespeichert || S.radar.konfig || {};
    if (quelle.sprachen || quelle.sprache) S.f.sprache = new Set(quelle.sprache || quelle.sprachen);
    if (quelle.produkte || quelle.typ) S.f.typ = new Set(quelle.typ || quelle.produkte);
    live();
    tab(location.hash.slice(1) || "radar", false);
  }

  $("#radar-grid").innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  laden();
  setInterval(() => { live(); }, 60000);
  setInterval(laden, 10 * 60000);
})();
