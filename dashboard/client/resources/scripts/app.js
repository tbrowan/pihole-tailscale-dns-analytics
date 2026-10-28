// Front end for the Pi-hole dashboard: fetches JSON from the Flask API (app.py) and draws it.

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = n => Number(n).toLocaleString();
const charts = {};
const STALE_MINUTES = 120;  // the collector runs hourly, so two missed runs means it broke

// [tile id, field from /api/latest, how to display the value]
const TILES = [
  ["t-total", "total_queries", fmt],
  ["t-blocked", "blocked_queries", fmt],
  ["t-pct", "percent_blocked", v => v.toFixed(1) + "%"],
  ["t-clients", "active_clients", fmt],
  ["t-unique", "unique_domains", fmt],
  ["t-gravity", "gravity_domains", fmt],
];

let topBlocked = { total_snapshots: 0, domains: [] };
let sort = { key: "snapshots_seen", dir: -1 };  // dir: 1 = ascending, -1 = descending

function label(iso) {
  const d = new Date(iso);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric" });
}

function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function baseOptions(extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { color: css("--muted") } } },
    scales: {
      x: { ticks: { color: css("--muted"), maxTicksLimit: 8 }, grid: { display: false } },
      y: { beginAtZero: true, ticks: { color: css("--muted") }, grid: { color: css("--border") } },
    },
    ...extra,
  };
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} returned ${r.status}`);
  return r.json();
}

function renderTiles(latest) {
  const prev = latest.day_before;
  for (const [id, field, show] of TILES) {
    const tile = document.getElementById(id);
    tile.querySelector(".value").textContent = show(latest[field]);
    let text = "";
    if (prev) {
      const isPct = field === "percent_blocked";
      const diff = isPct ? Math.round((latest[field] - prev[field]) * 10) / 10 : latest[field] - prev[field];
      const size = isPct ? Math.abs(diff).toFixed(1) + " pts" : fmt(Math.abs(diff));
      text = diff === 0 ? "Same as 24h ago" : `${diff > 0 ? "▲" : "▼"} ${size} vs 24h ago`;
    }
    tile.querySelector(".delta").textContent = text;
  }
}

function renderStale(latest) {
  const banner = document.getElementById("stale");
  banner.hidden = !(latest.age_minutes > STALE_MINUTES);
  banner.textContent = `No new snapshot for ${(latest.age_minutes / 60).toFixed(1)} hours. ` +
    "Check the collector's cron job and collector.log on the Pi.";
}

function renderTable() {
  const rows = [...topBlocked.domains].sort((a, b) => {
    const x = a[sort.key], y = b[sort.key];
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sort.dir;
  });
  document.getElementById("domain-rows").replaceChildren(...rows.map(d => {
    const tr = document.createElement("tr");
    const share = topBlocked.total_snapshots ? Math.round(d.snapshots_seen / topBlocked.total_snapshots * 100) : 0;
    for (const text of [d.domain, `${fmt(d.snapshots_seen)} (${share}%)`, fmt(d.peak_hits)]) {
      const td = document.createElement("td");
      td.textContent = text;  // textContent, not innerHTML: domain names come from DNS traffic and are untrusted
      tr.append(td);
    }
    return tr;
  }));
  document.querySelectorAll("th[data-key]").forEach(th => {
    const state = th.dataset.key !== sort.key ? "none" : sort.dir > 0 ? "ascending" : "descending";
    th.setAttribute("aria-sort", state);
  });
}

async function load() {
  const days = document.getElementById("range").value;
  const updated = document.getElementById("updated");
  try {
    const [latest, history, topData] = await Promise.all([
      getJSON("/api/latest"),
      getJSON(`/api/history?days=${days}`),
      getJSON(`/api/top-blocked?days=${days}`),
    ]);
    topBlocked = topData;

    if (latest.taken_at) {
      renderTiles(latest);
      renderStale(latest);
      updated.textContent =
        `Latest snapshot ${new Date(latest.taken_at).toLocaleString()} · ${history.length} snapshots in range`;
    } else {
      updated.textContent = "No snapshots yet";
    }

    const labels = history.map(r => label(r.taken_at));

    draw("pctChart", {
      type: "line",
      data: { labels, datasets: [{
        label: "% blocked", data: history.map(r => r.percent_blocked),
        borderColor: css("--blocked"), backgroundColor: css("--blocked"),
        pointRadius: 0, borderWidth: 2, tension: 0.25,
      }]},
      options: baseOptions({ plugins: { legend: { display: false } } }),
    });

    draw("volChart", {
      type: "line",
      data: { labels, datasets: [
        { label: "Total", data: history.map(r => r.total_queries),
          borderColor: css("--accent"), backgroundColor: css("--accent"),
          pointRadius: 0, borderWidth: 2, tension: 0.25 },
        { label: "Blocked", data: history.map(r => r.blocked_queries),
          borderColor: css("--blocked"), backgroundColor: css("--blocked"),
          pointRadius: 0, borderWidth: 2, tension: 0.25 },
      ]},
      options: baseOptions(),
    });

    document.getElementById("persist-note").textContent =
      `How many of the ${topBlocked.total_snapshots} hourly snapshots in range each domain appeared in the top-10 blocked list.`;

    draw("topChart", {
      type: "bar",
      data: {
        labels: topBlocked.domains.map(d => d.domain),
        datasets: [{ label: "Snapshots seen", data: topBlocked.domains.map(d => d.snapshots_seen),
                     backgroundColor: css("--blocked"), borderRadius: 4 }],
      },
      options: baseOptions({
        indexAxis: "y",
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { afterLabel: ctx =>
            `Peak hits in a 24h window: ${fmt(topBlocked.domains[ctx.dataIndex].peak_hits)}` } },
        },
        scales: {
          x: { beginAtZero: true, ticks: { color: css("--muted") }, grid: { color: css("--border") } },
          y: { ticks: { color: css("--text") }, grid: { display: false } },
        },
      }),
    });

    renderTable();
  } catch (err) {
    const span = document.createElement("span");
    span.className = "error";
    span.textContent = `Could not load data: ${err.message}`;
    updated.replaceChildren(span);
  }
}

document.querySelectorAll("th[data-key] button").forEach(btn => btn.addEventListener("click", () => {
  const key = btn.parentElement.dataset.key;
  // Same column flips direction; a new column starts A→Z for names, biggest-first for numbers.
  sort = key === sort.key ? { key, dir: -sort.dir } : { key, dir: key === "domain" ? 1 : -1 };
  renderTable();
}));
document.getElementById("range").addEventListener("change", load);
load();
setInterval(load, 5 * 60 * 1000);  // refresh every 5 minutes
