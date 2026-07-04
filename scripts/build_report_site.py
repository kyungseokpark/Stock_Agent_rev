"""Build a static report site from screening outputs.

The script intentionally uses only the standard library plus pandas because it
runs inside GitHub Actions after the screener has already installed project
dependencies.
"""

from __future__ import annotations

import argparse
import html
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


MARKETS = {
    "kr": "KR Market",
    "us": "US Market",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static screening report pages.")
    parser.add_argument("--output-dir", default="public", help="Directory to write the static site into.")
    parser.add_argument("--source-dir", default="output", help="Directory containing market output folders.")
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def copy_if_exists(source: Path, target_dir: Path) -> str:
    if not source.exists():
        return ""
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target.name


def fmt(value) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def first_existing(row: pd.Series, names: list[str]) -> str:
    for name in names:
        if name in row and pd.notna(row[name]):
            return fmt(row[name])
    return "-"


def table_html(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">No candidates were generated.</p>'

    columns = [
        ("rank", "Rank"),
        ("ticker", "Ticker"),
        ("name", "Name"),
        ("final_score", "Score"),
        ("decision", "Decision"),
        ("chart_type", "Pattern"),
        ("risk_reward", "R/R"),
        ("current_price", "Price"),
        ("stop_loss", "Stop"),
        ("target1", "Target 1"),
        ("target2", "Target 2"),
    ]
    visible = [(key, label) for key, label in columns if key in df.columns]
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in visible)
    rows = []
    for _, row in df.iterrows():
        cells = "".join(f"<td>{html.escape(first_existing(row, [key]))}</td>" for key, _ in visible)
        rows.append(f"<tr>{cells}</tr>")
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def markdown_preview(text: str, limit: int = 12000) -> str:
    if not text:
        return '<p class="empty">Markdown report is not available.</p>'
    clipped = text[:limit]
    if len(text) > limit:
        clipped += "\n\n...[truncated in page preview; download the Markdown for the full report]"
    return f"<pre>{html.escape(clipped)}</pre>"


def market_section(market: str, source_root: Path, site_root: Path) -> str:
    label = MARKETS[market]
    source_dir = source_root / market
    asset_dir = site_root / market
    top5_path = source_dir / "top5.csv"
    full_path = source_dir / "full_result.csv"
    report_path = source_dir / "claude_input_report.md"
    performance_path = source_dir / "performance_summary.txt"

    top5 = read_csv(top5_path)
    report_text = read_text(report_path)
    performance_text = read_text(performance_path)
    links = []
    for path, title in [
        (top5_path, "Top 5 CSV"),
        (full_path, "Full Result CSV"),
        (report_path, "Markdown Report"),
        (performance_path, "Performance Summary"),
    ]:
        copied_name = copy_if_exists(path, asset_dir)
        if copied_name:
            links.append(f'<a href="{market}/{html.escape(copied_name)}">{html.escape(title)}</a>')

    updated = "-"
    existing = [path for path in [top5_path, report_path, performance_path] if path.exists()]
    if existing:
        updated = datetime.fromtimestamp(max(path.stat().st_mtime for path in existing)).astimezone().strftime("%Y-%m-%d %H:%M %Z")

    link_html = '<div class="links">' + "".join(links) + "</div>" if links else ""
    performance_html = ""
    if performance_text:
        performance_html = f"<h3>Performance Tracking</h3><pre>{html.escape(performance_text)}</pre>"

    return f"""
    <section>
      <div class="section-head">
        <div>
          <h2>{html.escape(label)}</h2>
          <p>Last output update: {html.escape(updated)}</p>
        </div>
        {link_html}
      </div>
      {table_html(top5)}
      {performance_html}
      <h3>Report Preview</h3>
      {markdown_preview(report_text)}
    </section>
    """


def write_site(source_root: Path, site_root: Path) -> Path:
    if site_root.exists():
        shutil.rmtree(site_root)
    site_root.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    sections = "\n".join(market_section(market, source_root, site_root) for market in ["kr", "us"])
    index = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock Agent Daily Screening</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #126a5a;
      --accent-soft: #e5f3ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      padding: 32px max(20px, calc((100vw - 1180px) / 2)) 20px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px 20px 48px;
    }}
    h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 22px; }}
    h3 {{ font-size: 16px; margin-top: 24px; }}
    p {{ margin: 6px 0 0; color: var(--muted); }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .notice {{
      margin-top: 14px;
      max-width: 900px;
      color: var(--muted);
      font-size: 14px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 16px;
    }}
    .links {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      min-width: 220px;
    }}
    .links a {{
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid #b8ded4;
      border-radius: 6px;
      padding: 7px 10px;
      text-decoration: none;
      font-size: 13px;
      font-weight: 600;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 840px;
      font-size: 14px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: #f0f3f7;
      color: #344054;
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    pre {{
      margin: 12px 0 0;
      max-height: 520px;
      overflow: auto;
      background: #101828;
      color: #f2f4f7;
      border-radius: 8px;
      padding: 16px;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .empty {{
      padding: 16px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      header {{ padding-top: 24px; }}
      h1 {{ font-size: 23px; }}
      .section-head {{ display: block; }}
      .links {{ justify-content: flex-start; margin-top: 12px; }}
      section {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Stock Agent Daily Screening</h1>
    <p>Generated at {html.escape(generated_at)}</p>
    <div class="notice">
      This page publishes automated screening output only. It is not investment advice, and all prices,
      scores, and tracking results depend on the data available at the run time.
    </div>
  </header>
  <main>
    {sections}
  </main>
</body>
</html>
"""
    index_path = site_root / "index.html"
    index_path.write_text(index, encoding="utf-8")
    return index_path


def main() -> int:
    args = parse_args()
    index_path = write_site(Path(args.source_dir), Path(args.output_dir))
    print(f"Report site written: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
