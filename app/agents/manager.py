"""
Manager Agent
-------------
JOB: Orchestrate all agents in the correct sequence, passing outputs between them,
saving results after each step, and handling the overall pipeline flow.

CHANGE LOG v1:
  - Added out_dir.rstrip to fix double-slash in output paths
  - Step labels reflect which model is actually running

CHANGE LOG v2:
  - FIX: qa.run() now receives selected_products as third argument
    The QA agent uses this to look up supplier descriptions for each SKU,
    which it includes in the prompt as verified facts to prevent false positives.
    Without this, the QA model had no way to know which specs were supplier-confirmed.
"""

import json
import os
from app.llm.provider import get_provider
from app.agents import sourcing, listing, pricing, order_routing, qa, reporter

#shpyfy api
from app import shopify_sync


def save_json(data: list | dict, path: str):
    """Save data as pretty-printed JSON with UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Manager] Saved: {path}")

def run(catalog_path: str, orders_path: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    out_dir = out_dir.rstrip('/\\')

    print("\n" + "=" * 60)
    print("  SHOPIFY OPS AGENT — Starting pipeline")
    print("=" * 60)

    print("\n[Setup] Initialising LLM providers...")
    # listing_llm = get_provider("ollama_qwen3")
    # qa_llm      = get_provider("ollama_qwen3")
    listing_llm = get_provider("ollama_llama3")
    qa_llm      = get_provider("ollama_mistral")

    # ── Step 1: Product Sourcing ─────────────────────────────────
    print("\n[Step 1/7] Product Sourcing Agent")
    selected_products = sourcing.run(catalog_path)
    save_json(selected_products, f"{out_dir}/selection.json")

    # ── Step 2: Listing Generation ───────────────────────────────
    print(f"\n[Step 2/7] Listing Agent (LLM: {listing_llm.model})")
    listings = listing.run(selected_products, listing_llm)
    save_json(listings, f"{out_dir}/listings.json")

    # ── Step 3: Pricing & Stock ──────────────────────────────────
    print("\n[Step 3/7] Pricing & Stock Agent")
    prices, stocks = pricing.run(selected_products, out_dir)

    # ── Step 4: Order Routing ────────────────────────────────────
    print("\n[Step 4/7] Order Routing Agent")
    order_actions = order_routing.run(orders_path, catalog_path, selected_products, stocks)
    save_json(order_actions, f"{out_dir}/order_actions.json")

    # ── Step 5: QA Review ────────────────────────────────────────
    print(f"\n[Step 5/7] QA Agent (LLM: {qa_llm.model})")
    redlines = qa.run(listings, qa_llm, selected_products)
    save_json(redlines, f"{out_dir}/listing_redlines.json")

    # ── Step 6: Daily Report ─────────────────────────────────────
    # WHY REPORTER RUNS BEFORE SHOPIFY:
    #   The report always gets written even if Shopify fails.
    #   This way you always have a record of what the pipeline decided,
    #   regardless of whether the live sync succeeded.
    print("\n[Step 6/7] Reporter Agent")

    # ── Step 7: Shopify Sync ─────────────────────────────────────
    # WHY WE CHECK FOR THE TOKEN:
    #   If someone runs the pipeline without Shopify credentials,
    #   it still works perfectly — it just skips the sync step.
    #   This makes the pipeline useful in two modes:
    #     - Simulation mode (no .env Shopify credentials) → files only
    #     - Live mode (credentials present) → files + Shopify store updated
    sync_results = None
    if os.getenv("SHOPIFY_ACCESS_TOKEN"):
        print("\n[Step 7/7] Shopify Sync")
        sync_results = shopify_sync.run(
            selected_products, listings, prices, stocks
        )
    else:
        print("\n[Step 7/7] Shopify Sync — SKIPPED (no credentials in .env)")
        print("           Add SHOPIFY_SHOP_URL and SHOPIFY_ACCESS_TOKEN to enable.")

    # Reporter runs after sync so it can include sync results
    reporter.run(
        selected_products, listings, prices, stocks,
        order_actions, redlines, out_dir, sync_results
    )

    print("\n" + "=" * 60)
    print(f"  PIPELINE COMPLETE. All outputs in: {out_dir}/")
    print("=" * 60 + "\n")
