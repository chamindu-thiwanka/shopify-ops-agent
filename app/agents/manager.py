# """
# Manager Agent
# -------------
# JOB: Orchestrate all agents in the correct sequence, passing data between them,
#      saving outputs, and handling errors gracefully.

# WHY A DEDICATED MANAGER:
#   Without a manager, you'd have a long script where everything is jumbled
#   together. The manager makes the sequence explicit and readable.
#   It also means you can re-run individual stages during development
#   (e.g., skip re-running the slow LLM listing step if you're just
#   testing the reporter).

# ORCHESTRATION PATTERN:
#   Manager → Sourcing → Listing → Pricing → Orders → QA → Reporter
#   Each agent's output becomes the next agent's input.
#   All outputs are saved to disk immediately after each step (so a
#   crash at step 5 doesn't lose steps 1-4).
# """

# import json
# import os
# from app.llm.provider import get_provider
# from app.agents import sourcing, listing, pricing, order_routing, qa, reporter


# def save_json(data: list | dict, path: str):
#     """Save any data as pretty-printed JSON."""
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=2, ensure_ascii=False)
#     print(f"  [Manager] Saved: {path}")


# def run(catalog_path: str, orders_path: str, out_dir: str):
#     os.makedirs(out_dir, exist_ok=True)
#     print("\n" + "="*60)
#     print("  SHOPIFY OPS AGENT — Starting pipeline")
#     print("="*60)

#     # — Assign LLMs to agents —
#     # WHY DIFFERENT MODELS: Listing needs creative writing (llama3 is stronger here).
#     # QA needs critical analysis (mistral handles this well). This satisfies the
#     # multi-LLM requirement and is genuinely good architecture.
#     print("\n[Setup] Initialising LLM providers...")
#     listing_llm = get_provider("ollama_qwen3")
#     qa_llm = get_provider("ollama_qwen3")

#     # STEP 1 — Product Sourcing
#     print("\n[Step 1/6] Product Sourcing Agent")
#     selected_products = sourcing.run(catalog_path)
#     save_json(selected_products, f"{out_dir}/selection.json")

#     # STEP 2 — Listing Generation
#     print("\n[Step 2/6] Listing Agent (LLM: llama3)")
#     listings = listing.run(selected_products, listing_llm)
#     save_json(listings, f"{out_dir}/listings.json")

#     # STEP 3 — Pricing & Stock
#     print("\n[Step 3/6] Pricing & Stock Agent")
#     prices, stocks = pricing.run(selected_products, out_dir)

#     # STEP 4 — Order Routing
#     print("\n[Step 4/6] Order Routing Agent")
#     order_actions = order_routing.run(orders_path, catalog_path, selected_products, stocks)
#     save_json(order_actions, f"{out_dir}/order_actions.json")

#     # STEP 5 — QA Review
#     print("\n[Step 5/6] QA Agent (LLM: mistral)")
#     redlines = qa.run(listings, qa_llm)
#     save_json(redlines, f"{out_dir}/listing_redlines.json")

#     # STEP 6 — Daily Report
#     print("\n[Step 6/6] Reporter Agent")
#     reporter.run(selected_products, listings, prices, stocks, order_actions, redlines, out_dir)

#     print("\n" + "="*60)
#     print(f"  PIPELINE COMPLETE. All outputs in: {out_dir}/")
#     print("="*60 + "\n")

"""
Manager Agent
-------------
JOB: Orchestrate all agents in the correct sequence, passing outputs between them,
saving results after each step, and handling the overall pipeline flow.

WHY A DEDICATED MANAGER:
  Without a manager, all the logic would be one long script. The manager
  makes the sequence explicit, readable, and easy to modify. It also means
  you can clearly see which LLM is assigned to which agent — important for
  satisfying the multi-LLM requirement.

CHANGE LOG:
  - Added out_dir.rstrip('/\\') to fix double-slash in output paths (out//file.json)
  - Step labels now accurately reflect which model is being used
  - Comments updated to explain LLM assignment decisions clearly
"""

import json
import os
from app.llm.provider import get_provider
from app.agents import sourcing, listing, pricing, order_routing, qa, reporter


def save_json(data: list | dict, path: str):
    """Save data as pretty-printed JSON with UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [Manager] Saved: {path}")


def run(catalog_path: str, orders_path: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    # FIX: Strip trailing slashes to prevent double-slash in output paths (out//file.json)
    out_dir = out_dir.rstrip('/\\')

    print("\n" + "=" * 60)
    print("  SHOPIFY OPS AGENT — Starting pipeline")
    print("=" * 60)

    # ── LLM Assignment ──────────────────────────────────────────
    # WHY TWO DIFFERENT PROVIDERS:
    #   listing_llm → creative writing task → needs generative capability
    #   qa_llm      → critical analysis task → needs focused, skeptical reasoning
    #
    #   Currently both set to qwen3:1.7b for local testing (fast, low RAM).
    #   For final submission: swap to ollama_llama3 and ollama_mistral.
    #   Only these two lines need to change — nothing else in the codebase.
    print("\n[Setup] Initialising LLM providers...")
    listing_llm = get_provider("ollama_qwen3")   # swap to "ollama_llama3" for submission
    qa_llm      = get_provider("ollama_qwen3")   # swap to "ollama_mistral" for submission

    # ── Step 1: Product Sourcing ─────────────────────────────────
    # Pure logic — no LLM. Filters catalog and scores products.
    print("\n[Step 1/6] Product Sourcing Agent")
    selected_products = sourcing.run(catalog_path)
    save_json(selected_products, f"{out_dir}/selection.json")

    # ── Step 2: Listing Generation ───────────────────────────────
    # LLM writes titles, bullets, descriptions, tags, SEO fields.
    print(f"\n[Step 2/6] Listing Agent (LLM: {listing_llm.model})")
    listings = listing.run(selected_products, listing_llm)
    save_json(listings, f"{out_dir}/listings.json")

    # ── Step 3: Pricing & Stock ──────────────────────────────────
    # Pure math — calculates sell prices and stock status. Writes CSVs directly.
    print("\n[Step 3/6] Pricing & Stock Agent")
    prices, stocks = pricing.run(selected_products, out_dir)

    # ── Step 4: Order Routing ────────────────────────────────────
    # Pure logic — routes each order to fulfil/backorder/substitute.
    print("\n[Step 4/6] Order Routing Agent")
    order_actions = order_routing.run(orders_path, catalog_path, selected_products, stocks)
    save_json(order_actions, f"{out_dir}/order_actions.json")

    # ── Step 5: QA Review ────────────────────────────────────────
    # Second LLM reviews listings for over-claims and false specs.
    print(f"\n[Step 5/6] QA Agent (LLM: {qa_llm.model})")
    redlines = qa.run(listings, qa_llm)
    save_json(redlines, f"{out_dir}/listing_redlines.json")

    # ── Step 6: Daily Report ─────────────────────────────────────
    # Pure Python — summarises everything into daily_report.md.
    print("\n[Step 6/6] Reporter Agent")
    reporter.run(selected_products, listings, prices, stocks, order_actions, redlines, out_dir)

    print("\n" + "=" * 60)
    print(f"  PIPELINE COMPLETE. All outputs in: {out_dir}/")
    print("=" * 60 + "\n")