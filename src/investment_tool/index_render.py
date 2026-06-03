"""Render source-aware local HTML indexes for captured evidence."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any

from investment_tool.render_utils import display_token


def source_display(entry: dict[str, Any]) -> str:
    return str(
        entry.get("source_display")
        or entry.get("source_label")
        or entry.get("source_platform")
        or entry.get("source")
        or "X"
    )


def source_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return slug[:90] or "source"


def render_index(path: Path, entries: list[dict[str, Any]], title: str = "Thread Capture Index") -> None:
    all_threads_rel = "index.html" if path.parent.name == "indexes" else "../index.html"
    root = path.parent.parent if path.parent.name == "indexes" else path.parent.parent.parent
    owned_json_rel = os.path.relpath(root / "indexes" / "current_owned.json", path.parent)

    def index_rel(*parts: str) -> str:
        return os.path.relpath(root.joinpath("indexes", *parts), path.parent)

    records: list[dict[str, Any]] = []
    for entry in entries:
        tickers = entry["tickers"] or []
        tags = entry["tags"] or []
        primary_ticker = entry.get("primary_ticker") or (tickers[0] if tickers else "UNKNOWN")
        flags = entry.get("flags") or []
        category = entry.get("category") or ""
        source_text = source_display(entry)
        source_href = index_rel("by_source", f"{source_slug(source_text)}.html")
        records.append(
            {
                "date": entry.get("created_at") or entry["date"],
                "source": source_text,
                "sourceHref": source_href,
                "priority": entry.get("priority") or "Pending",
                "signal": entry.get("signal") or "Pending",
                "ticker": primary_ticker,
                "title": entry["title"],
                "threadHref": os.path.relpath(entry["abs_path"], path.parent),
                "type": entry["type"],
                "typeHref": index_rel("by_type", f"{entry['type']}.html"),
                "category": category or "Pending",
                "categoryDisplay": display_token(category) if category else "Pending",
                "categoryHref": index_rel("by_tag", f"{category}.html") if category else all_threads_rel,
                "stance": entry.get("stance") or "Pending",
                "stanceDisplay": display_token(entry.get("stance")) if entry.get("stance") else "Pending",
                "score": entry.get("actionability_score") or 0,
                "flagsText": " ".join(flags),
                "flags": [{"label": display_token(flag), "href": index_rel("by_tag", f"{flag}.html")} for flag in flags],
                "tickerText": primary_ticker if primary_ticker != "UNKNOWN" else "none",
                "tickers": [
                    {"label": primary_ticker, "href": index_rel("by_ticker", f"{primary_ticker}.html"), "ticker": primary_ticker}
                ]
                if primary_ticker != "UNKNOWN"
                else [],
                "tagText": " ".join(tags),
                "posts": entry["posts"],
                "sourcePosts": entry["source_posts"],
                "photos": entry["photos"],
            }
        )
    records_json = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<link href="https://unpkg.com/tabulator-tables@6.3.1/dist/css/tabulator.min.css" rel="stylesheet">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;color:#15202b;background:#f5f7fa;font-size:12px}}
.shell{{padding:18px 22px 28px}}
.topbar{{display:flex;align-items:center;gap:12px;justify-content:space-between;margin-bottom:12px}}
h1{{font-size:20px;line-height:1.2;margin:0;letter-spacing:0}}
.actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.actions a,.actions button{{border:1px solid #cfd8e3;background:#fff;color:#15202b;border-radius:6px;padding:6px 9px;text-decoration:none;font-size:12px;cursor:pointer}}
.actions a:hover,.actions button:hover{{border-color:#1d9bf0;background:#f0f8ff}}
.count{{color:#5b7083;font-size:12px}}
.grid-wrap{{height:calc(100vh - 88px);border:1px solid #d8e1ea;border-radius:8px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.05)}}
#thread-grid{{height:100%}}
.tabulator{{border:0;background:#fff;font-size:12px}}
.tabulator .tabulator-header{{border-bottom:1px solid #d8e1ea;background:#f8fafc;color:#3c4b5d;font-weight:700}}
.tabulator .tabulator-header .tabulator-col{{background:#f8fafc;border-right:1px solid #e6edf3}}
.tabulator .tabulator-header .tabulator-col.tabulator-sortable:hover{{background:#eef6ff}}
.tabulator .tabulator-header .tabulator-col-title{{font-size:11px;text-transform:uppercase;letter-spacing:.03em;line-height:1.2;white-space:normal}}
.tabulator .tabulator-header-filter input{{height:24px;border:1px solid #cfd8e3;border-radius:5px;padding:2px 6px;font-size:11px;background:#fff}}
.tabulator .tabulator-header-filter input:focus{{outline:0;border-color:#1d9bf0;box-shadow:0 0 0 2px rgba(29,155,240,.12)}}
.tabulator-row{{min-height:34px;border-bottom:1px solid #edf1f5}}
.tabulator-row .tabulator-cell{{border-right:1px solid #edf1f5;padding:6px 8px;line-height:1.25;white-space:normal}}
.tabulator-row.tabulator-row-even{{background:#fbfcfe}}
.tabulator-row:hover{{background:#f3f9ff}}
.thread-link{{display:block;color:#111827;text-decoration:none;font-weight:650;line-height:1.25}}
.thread-link:hover{{color:#0b75c9;text-decoration:underline}}
.priority{{display:inline-block;min-width:22px;text-align:center;border-radius:5px;padding:2px 5px;font-weight:800;background:#eef2f7;color:#243447}}
.priority.p0,.priority.p1{{background:#fff1f2;color:#9f1239;border:1px solid #fecdd3}}
.signal{{font-weight:700;color:#243447}}
.signal.buy_signal,.signal.sell_signal,.signal.trim_signal{{color:#9f1239}}
.pill{{display:inline-block;padding:1px 7px;margin:1px 3px 2px 0;border:1px solid #c7d3df;border-radius:999px;text-decoration:none;color:#243447;background:#fff;font-size:10.5px;line-height:1.45;white-space:nowrap}}
.pill:hover{{border-color:#1d9bf0;background:#edf8ff}}
.pill.type,.pill.tag{{background:#f8fafc;color:#34495e;border-color:#d7e0ea}}
.pill.owned{{border-color:#0f766e;background:#e8f7f4;color:#075e57;font-weight:750}}
.pill.muted{{color:#6b7c8f;background:#f7f9fb}}
.source-label{{color:#34495e;font-weight:650}}
.num{{font-variant-numeric:tabular-nums;text-align:right;display:block}}
.fallback{{display:none;margin:12px 0;padding:10px 12px;border:1px solid #f0c36d;background:#fff7da;border-radius:6px;color:#594100}}
</style></head>
<body><div class="shell">
<div class="topbar">
  <h1>{html.escape(title)}</h1>
  <div class="actions">
    <a href="{html.escape(all_threads_rel)}">All threads</a>
    <button id="clearFilters" type="button">Clear filters</button>
    <span class="count"><span id="visibleCount">{len(entries)}</span> / {len(entries)} shown</span>
  </div>
</div>
<div id="libraryWarning" class="fallback">The grid library did not load. Check internet access, then refresh this local HTML file.</div>
<div class="grid-wrap"><div id="thread-grid"></div></div>
<script src="https://unpkg.com/tabulator-tables@6.3.1/dist/js/tabulator.min.js"></script>
<script>
const tableData = {records_json};
tableData.sort((a, b) => b.date.localeCompare(a.date) || a.source.localeCompare(b.source) || a.ticker.localeCompare(b.ticker) || a.title.localeCompare(b.title));
function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function relTime(iso) {{
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  if (diff < 86400*2) return 'yesterday';
  if (diff < 86400*7) return Math.floor(diff/86400) + ' days ago';
  if (diff < 86400*30) return Math.floor(diff/86400/7) + ' weeks ago';
  return new Date(iso).toLocaleDateString();
}}
function dateHtml(iso) {{
  const safeIso = escapeHtml(iso);
  return `<span class='rel-time' data-ts='${{safeIso}}' title='${{safeIso}}'>${{relTime(iso)}}</span>`;
}}
function updateRelativeTimes() {{
  document.querySelectorAll('.rel-time[data-ts]').forEach(el => {{
    const iso = el.dataset.ts;
    el.textContent = relTime(iso);
    el.title = iso;
  }});
}}
function pillHtml(items, cls) {{
  if (!items || !items.length) return "<span class='pill muted'>none</span>";
  return items.map(item => {{
    const tickerAttr = item.ticker ? ` data-ticker='${{escapeHtml(item.ticker)}}'` : '';
    const tickerCls = item.ticker ? ' ticker-pill' : '';
    return `<a class='pill ${{cls}}${{tickerCls}}'${{tickerAttr}} href='${{escapeHtml(item.href)}}'>${{escapeHtml(item.label)}}</a>`;
  }}).join(' ');
}}
async function applyOwnedColoring() {{
  try {{
    const response = await fetch("{html.escape(owned_json_rel)}", {{cache: "no-store"}});
    if (!response.ok) return;
    const data = await response.json();
    const owned = new Set((data.owned_tickers || []).map(t => String(t).toUpperCase()));
    document.querySelectorAll("[data-ticker]").forEach(el => {{
      if (owned.has(String(el.dataset.ticker || "").toUpperCase())) el.classList.add("owned");
    }});
  }} catch (err) {{}}
}}
function priorityHtml(value) {{
  const display = value || 'Pending';
  const cls = String(display).toLowerCase();
  return `<span class='priority ${{escapeHtml(cls)}}'>${{escapeHtml(display)}}</span>`;
}}
function signalHtml(value) {{
  const display = value || 'Pending';
  const cls = String(display).toLowerCase();
  return `<span class='signal ${{escapeHtml(cls)}}'>${{escapeHtml(String(display).replaceAll('_', ' '))}}</span>`;
}}
function containsFilter(headerValue, rowValue) {{
  if (!headerValue) return true;
  return String(rowValue ?? '').toLowerCase().includes(String(headerValue).toLowerCase());
}}
function numberAtLeast(headerValue, rowValue) {{
  if (headerValue === '' || headerValue == null) return true;
  const wanted = Number(headerValue);
  return Number.isNaN(wanted) ? true : Number(rowValue) >= wanted;
}}
if (!window.Tabulator) {{
  document.getElementById('libraryWarning').style.display = 'block';
}} else {{
  const grid = new Tabulator('#thread-grid', {{
    data: tableData,
    height: '100%',
    layout: 'fitDataStretch',
    movableColumns: true,
    resizableColumnFit: true,
    reactiveData: false,
    initialSort: [{{column: 'date', dir: 'desc'}}],
    placeholder: 'No matching threads',
    columns: [
      {{title: 'Date', field: 'date', width: 92, sorter: 'string', headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => dateHtml(cell.getValue())}},
      {{title: 'Source', field: 'source', width: 150, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => `<a class='source-label' href='${{escapeHtml(cell.getRow().getData().sourceHref)}}'>${{escapeHtml(cell.getValue())}}</a>`}},
      {{title: 'Priority', field: 'priority', width: 86, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => priorityHtml(cell.getValue())}},
      {{title: 'Signal', field: 'signal', width: 132, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => signalHtml(cell.getValue())}},
      {{title: 'Tickers', field: 'tickerText', width: 150, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => pillHtml(cell.getRow().getData().tickers, '')}},
      {{title: 'Title', field: 'title', width: 430, minWidth: 260, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => `<a class='thread-link' href='${{escapeHtml(cell.getRow().getData().threadHref)}}'>${{escapeHtml(cell.getValue())}}</a>`}},
      {{title: 'Category', field: 'category', width: 140, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => `<a class='pill type' href='${{escapeHtml(cell.getRow().getData().categoryHref)}}'>${{escapeHtml(cell.getRow().getData().categoryDisplay)}}</a>`}},
      {{title: 'Stance', field: 'stance', width: 96, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => escapeHtml(cell.getRow().getData().stanceDisplay)}},
      {{title: 'Score >=', field: 'score', width: 86, hozAlign: 'right', sorter: 'number', headerFilter: 'input', headerFilterFunc: numberAtLeast, formatter: cell => `<span class='num'>${{cell.getValue()}}</span>`}},
      {{title: 'Flags', field: 'flagsText', width: 190, headerFilter: 'input', headerFilterFunc: containsFilter, formatter: cell => pillHtml(cell.getRow().getData().flags, 'tag')}},
      {{title: 'Posts >=', field: 'posts', width: 82, hozAlign: 'right', sorter: 'number', headerFilter: 'input', headerFilterFunc: numberAtLeast, formatter: cell => `<span class='num'>${{cell.getValue()}}</span>`}},
      {{title: 'Source >=', field: 'sourcePosts', width: 72, hozAlign: 'right', sorter: 'number', headerFilter: 'input', headerFilterFunc: numberAtLeast, formatter: cell => `<span class='num'>${{cell.getValue()}}</span>`}},
    ],
  }});
  const count = document.getElementById('visibleCount');
  function updateCount() {{
    count.textContent = grid.getRows('active').length;
  }}
  grid.on('tableBuilt', () => {{
    grid.setSort([{{column: 'date', dir: 'desc'}}]);
    updateRelativeTimes();
    applyOwnedColoring();
    updateCount();
  }});
  grid.on('dataFiltered', () => {{ updateRelativeTimes(); applyOwnedColoring(); updateCount(); }});
  grid.on('dataSorted', () => {{ updateRelativeTimes(); applyOwnedColoring(); updateCount(); }});
  document.getElementById('clearFilters').addEventListener('click', () => {{
    grid.clearHeaderFilter();
    grid.clearSort();
    grid.setSort([{{column: 'date', dir: 'desc'}}]);
    updateRelativeTimes();
    updateCount();
  }});
  setInterval(updateRelativeTimes, 60 * 1000);
  updateRelativeTimes();
  applyOwnedColoring();
  updateCount();
}}
</script>
</div></body></html>""",
        encoding="utf-8",
    )


def render_all_indexes(root: Path, entries: list[dict[str, Any]], owned_tickers: set[str]) -> None:
    indexes = root / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    owned_snapshot = {
        "content_type": "current_owned_tickers",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "owned_tickers": sorted(owned_tickers),
        "note": "Browser-only UI coloring snapshot. Do not upload as thread evidence.",
    }
    (indexes / "current_owned.json").write_text(json.dumps(owned_snapshot, indent=2), encoding="utf-8")
    for subdir in ("by_ticker", "by_type", "by_tag", "daily", "by_source"):
        for stale in (indexes / subdir).glob("*.html"):
            stale.unlink(missing_ok=True)
    sorted_entries = sorted(entries, key=lambda e: (e.get("created_at") or e["date"], e["label"], e["title"]), reverse=True)
    render_index(indexes / "index.html", sorted_entries, "All Captured Threads")
    for source in sorted({source_display(entry) for entry in entries}):
        render_index(
            indexes / "by_source" / f"{source_slug(source)}.html",
            [e for e in sorted_entries if source_display(e) == source],
            f"Threads from {source}",
        )
    for ticker in sorted({ticker for entry in entries for ticker in entry["tickers"]}):
        render_index(indexes / "by_ticker" / f"{ticker}.html", [e for e in sorted_entries if ticker in e["tickers"]], f"Threads for {ticker}")
    for thread_type in sorted({entry["type"] for entry in entries}):
        render_index(indexes / "by_type" / f"{thread_type}.html", [e for e in sorted_entries if e["type"] == thread_type], f"{thread_type} Threads")
    for tag in sorted({tag for entry in entries for tag in entry["tags"]}):
        render_index(
            indexes / "by_tag" / f"{tag}.html",
            [e for e in sorted_entries if tag in e["tags"]],
            f"Threads tagged {display_token(tag)}",
        )
    for date in sorted({entry["date"] for entry in entries}, reverse=True):
        render_index(indexes / "daily" / f"{date}.html", [e for e in sorted_entries if e["date"] == date], f"Threads captured for {date}")
