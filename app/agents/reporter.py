# """
# Reporter Agent
# --------------
# JOB: Summarise everything into a daily_report.md that a real business 
# owner could read over morning coffee.

# WHY MARKDOWN:
#   Markdown renders beautifully on GitHub (which is where you'll push this),
#   in most business tools like Notion and Confluence, and can be easily
#   converted to PDF. It's the standard format for developer reports.

# WHY NO LLM:
#   The report is a structured summary of data we already have.
#   Using an LLM would add latency and risk hallucination
#   (making up numbers that aren't in the data). Pure Python
#   string formatting gives us exact, trustworthy numbers.

# OUTPUT: daily_report.md
# """

# from datetime import date


# def run(
#     selected: list[dict],
#     listings: list[dict],
#     prices: list[dict],
#     stocks: list[dict],
#     orders: list[dict],
#     redlines: list[dict],
#     out_dir: str
# ) -> str:
#     today = date.today().isoformat()
    
#     # — Order stats —
#     total_orders = len(orders)
#     fulfilled = sum(1 for o in orders if o['action'] == 'fulfil')
#     backordered = sum(1 for o in orders if o['action'] == 'backorder')
#     substituted = sum(1 for o in orders if o['action'] == 'substitute')
    
#     # — Margin stats —
#     avg_margin = sum(p['margin_pct_au'] for p in prices) / len(prices) if prices else 0
#     top_margin = max(prices, key=lambda p: p['margin_pct_au']) if prices else {}
    
#     # — QA stats —
#     ok_count = sum(1 for r in redlines if r.get('severity') == 'ok')
#     minor_count = sum(1 for r in redlines if r.get('severity') == 'minor')
#     major_count = sum(1 for r in redlines if r.get('severity') == 'major')
#     major_issues = [r for r in redlines if r.get('severity') == 'major']
    
#     # — Stock alerts —
#     reorder_needed = [s for s in stocks if s['needs_reorder']]
    
#     # — Build report —
#     report = f"""# Daily Ops Report — {today}

# ## Executive Summary
# | Metric | Value |
# |--------|-------|
# | Products selected for listing | {len(selected)} |
# | Listings generated | {len(listings)} |
# | Average margin (AU) | {avg_margin:.1f}% |
# | Total orders processed | {total_orders} |
# | QA issues found | {major_count} major, {minor_count} minor |

# ---

# ## Product Selection
# {len(selected)} products were selected from the supplier catalog based on stock ≥ 10 and margin ≥ 25%.

# ### Top 5 Products by Margin
# | SKU | Name | Sell Price (AU) | Margin |
# |-----|------|----------------|--------|
# {chr(10).join(f"| {p['supplier_sku']} | {p['name'][:35]} | ${p['sell_price_au']:.2f} | {p['margin_pct_au']}% |" for p in sorted(prices, key=lambda x: x['margin_pct_au'], reverse=True)[:5])}

# Best performer: **{top_margin.get('name', 'N/A')}** at {top_margin.get('margin_pct_au', 0)}% margin.

# ---

# ## Order Routing Summary
# | Action | Count | % of Orders |
# |--------|-------|------------|
# | Fulfilled ✓ | {fulfilled} | {round(fulfilled/total_orders*100) if total_orders else 0}% |
# | Backordered ⏳ | {backordered} | {round(backordered/total_orders*100) if total_orders else 0}% |
# | Substituted ↔ | {substituted} | {round(substituted/total_orders*100) if total_orders else 0}% |
# | **Total** | **{total_orders}** | 100% |

# ### Order Details
# | Order ID | SKU | Qty | Country | Action | Note |
# |----------|-----|-----|---------|--------|------|
# {chr(10).join(f"| {o['order_id']} | {o['sku']} | {o['quantity']} | {o['customer_country']} | {o['action'].upper()} | {o['note'][:50]} |" for o in orders)}

# ---

# ## QA Review
# | Result | Count |
# |--------|-------|
# | Passed ✓ | {ok_count} |
# | Minor issues | {minor_count} |
# | Major issues ⚠️ | {major_count} |

# {f"### Major Issues Requiring Action{chr(10)}" + chr(10).join(f"- **{r['sku']}**: {'; '.join(r['issues'][:2])}" + chr(10) + f"  Fix: {r['suggested_fix']}" for r in major_issues) if major_issues else "No major QA issues found."}

# ---

# ## Stock Alerts
# {f"The following {len(reorder_needed)} products need reordering:" if reorder_needed else "No stock alerts — all products above reorder threshold."}
# {chr(10).join(f"- **{s['supplier_sku']}** ({s['name'][:30]}): {s['available_stock']} units remaining" for s in reorder_needed)}

# ---

# *Report generated automatically by Shopify Ops Agent on {today}.*
# """

#     with open(f"{out_dir}/daily_report.md", "w", encoding="utf-8") as f:
#         f.write(report)
    
#     print(f"  [Reporter] daily_report.md written.")
#     return report

"""
Reporter Agent
--------------
JOB: Summarise everything into a daily_report.md that a real business
owner could read. Covers product selection, orders, QA, stock alerts,
and — when credentials are present — Shopify sync results.

WHY NO LLM:
  The report is a structured summary of data we already have.
  Using an LLM would add latency and risk hallucination.
  Pure Python string formatting gives exact, trustworthy numbers.

CHANGE LOG v2:
  - Added optional sync_results parameter for Shopify section
  - Report note column widened from 50 to 80 chars
  - Shopify section only appears when sync actually ran
"""

from datetime import date


def run(
    selected: list[dict],
    listings: list[dict],
    prices: list[dict],
    stocks: list[dict],
    orders: list[dict],
    redlines: list[dict],
    out_dir: str,
    sync_results: dict = None       # None when Shopify sync was skipped
) -> str:

    today = date.today().isoformat()

    # ── Order stats ──────────────────────────────────────────────
    total_orders = len(orders)
    fulfilled    = sum(1 for o in orders if o['action'] == 'fulfil')
    backordered  = sum(1 for o in orders if o['action'] == 'backorder')
    substituted  = sum(1 for o in orders if o['action'] == 'substitute')

    # ── Margin stats ─────────────────────────────────────────────
    avg_margin = sum(p['margin_pct_au'] for p in prices) / len(prices) if prices else 0
    top_margin = max(prices, key=lambda p: p['margin_pct_au']) if prices else {}

    # ── QA stats ─────────────────────────────────────────────────
    ok_count    = sum(1 for r in redlines if r.get('severity') == 'ok')
    minor_count = sum(1 for r in redlines if r.get('severity') == 'minor')
    major_count = sum(1 for r in redlines if r.get('severity') == 'major')
    major_issues = [r for r in redlines if r.get('severity') == 'major']

    # ── Stock alerts ─────────────────────────────────────────────
    reorder_needed = [s for s in stocks if s['needs_reorder']]

    # ── Shopify sync section ──────────────────────────────────────
    # WHY CONDITIONAL:
    #   sync_results is None when the pipeline ran without Shopify credentials.
    #   We don't want the report to show a broken Shopify section in that case.
    #   When sync_results is present, we show exactly what happened.
    if sync_results and not sync_results.get("skipped"):
        shopify_section = f"""
---

## Shopify Sync
Products were pushed live to the Shopify store automatically.

| Action | Count |
|--------|-------|
| Products created ✓ | {sync_results.get('created', 0)} |
| Products updated ↻ | {sync_results.get('updated', 0)} |
| Failed ✗ | {sync_results.get('failed', 0)} |

"""
    elif sync_results and sync_results.get("skipped"):
        shopify_section = "\n---\n\n## Shopify Sync\nSkipped — credentials not configured.\n"
    else:
        shopify_section = "\n---\n\n## Shopify Sync\nNot configured — running in simulation mode.\n"

    # ── Build the full report ─────────────────────────────────────
    report = f"""# Daily Ops Report — {today}

## Executive Summary
| Metric | Value |
|--------|-------|
| Products selected for listing | {len(selected)} |
| Listings generated | {len(listings)} |
| Average margin (AU) | {avg_margin:.1f}% |
| Total orders processed | {total_orders} |
| QA issues found | {major_count} major, {minor_count} minor |

---

## Product Selection
{len(selected)} products were selected from the supplier catalog based on stock ≥ 10 and margin ≥ 25%.

### Top 5 Products by Margin
| SKU | Name | Sell Price (AU) | Margin |
|-----|------|----------------|--------|
{chr(10).join(
    f"| {p['supplier_sku']} | {p['name'][:35]} | ${p['sell_price_au']:.2f} | {p['margin_pct_au']}% |"
    for p in sorted(prices, key=lambda x: x['margin_pct_au'], reverse=True)[:5]
)}

Best performer: **{top_margin.get('name', 'N/A')}** at {top_margin.get('margin_pct_au', 0)}% margin.

---

## Order Routing Summary
| Action | Count | % of Orders |
|--------|-------|------------|
| Fulfilled ✓ | {fulfilled} | {round(fulfilled/total_orders*100) if total_orders else 0}% |
| Backordered ⏳ | {backordered} | {round(backordered/total_orders*100) if total_orders else 0}% |
| Substituted ↔ | {substituted} | {round(substituted/total_orders*100) if total_orders else 0}% |
| **Total** | **{total_orders}** | 100% |

### Order Details
| Order ID | SKU | Qty | Country | Action | Note |
|----------|-----|-----|---------|--------|------|
{chr(10).join(
    f"| {o['order_id']} | {o['sku']} | {o['quantity']} | {o['customer_country']} | {o['action'].upper()} | {o['note'][:80]} |"
    for o in orders
)}

---

## QA Review
| Result | Count |
|--------|-------|
| Passed ✓ | {ok_count} |
| Minor issues | {minor_count} |
| Major issues ⚠️ | {major_count} |

{
    "### Major Issues Requiring Action" + chr(10) +
    chr(10).join(
        f"- **{r['sku']}**: {'; '.join(r.get('issues', [])[:2])}" + chr(10) +
        f"  Fix: {r.get('suggested_fix', 'none')}"
        for r in major_issues
    )
    if major_issues else "No major QA issues found. ✓"
}

---

## Stock Alerts
{
    f"The following {len(reorder_needed)} products need reordering:" + chr(10) +
    chr(10).join(
        f"- **{s['supplier_sku']}** ({s['name'][:30]}): {s['available_stock']} units remaining"
        for s in reorder_needed
    )
    if reorder_needed else "No stock alerts — all products above reorder threshold. ✓"
}
{shopify_section}
---

*Report generated automatically by Shopify Ops Agent on {today}.*
"""

    with open(f"{out_dir}/daily_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"  [Reporter] daily_report.md written.")
    return report