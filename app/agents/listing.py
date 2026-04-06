"""
Listing Agent
-------------
JOB: Use an LLM to write compelling Shopify product listings.

WHY AN LLM HERE:
  Writing product titles, bullet points, and descriptions that are
  persuasive, SEO-optimised, and engaging requires language creativity.
  This is exactly what LLMs excel at.

CHANGE LOG:
  - Prompt now explicitly forbids ** markdown bold in bullet points
  - Bullet format enforced: "Keyword — benefit" plain text only
  - Added explicit ban on unverifiable claims (warranties, world's best, etc.)
  - SEO description strictly capped at 160 chars in prompt instruction
  - Added example bullet format so the model has a clear pattern to follow
"""

import json
import re
from app.llm.provider import LLMProvider

SYSTEM_PROMPT = """You are an expert Shopify product copywriter specialising in
dropshipping stores. You write compelling, accurate, SEO-optimised product listings.

CRITICAL: Return ONLY valid JSON. No markdown fences. No explanation. No preamble.
The JSON must be parseable by Python's json.loads() directly."""


LISTING_TEMPLATE = """Write a complete Shopify product listing for this product.

PRODUCT DETAILS:
- SKU: {supplier_sku}
- Name: {name}
- Category: {category}
- Brand: {brand}
- Description from supplier: {description}
- Cost price: ${cost_price} (do NOT mention this in the listing)

STRICT REQUIREMENTS:
- Title: under 70 characters, include main keyword naturally, no brand name repetition
- Bullets: exactly 5 items, PLAIN TEXT ONLY — absolutely no **, no markdown, no asterisks
  Format each bullet as: "Keyword — benefit description"
  Example: "Battery life — lasts up to 30 hours on a single charge"
- Description: 2-3 short paragraphs, honest and persuasive
  FORBIDDEN: "world's best", "100% warranty", "proven to", "guaranteed to cure",
  "fastest ever", or any claim the supplier description does not support
- Tags: 8 relevant lowercase single-word or short-phrase tags
- SEO title: under 60 characters
- SEO description: under 160 characters, plain text only

Return this exact JSON structure with no extra fields:
{{
  "supplier_sku": "{supplier_sku}",
  "title": "string under 70 chars",
  "bullets": [
    "Keyword one — plain text benefit",
    "Keyword two — plain text benefit",
    "Keyword three — plain text benefit",
    "Keyword four — plain text benefit",
    "Keyword five — plain text benefit"
  ],
  "description": "paragraph one. paragraph two. paragraph three.",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],
  "seo_title": "string under 60 chars",
  "seo_description": "string under 160 chars"
}}"""


def _clean_bullets(bullets: list) -> list:
    """
    Post-process bullets to strip any markdown the LLM sneaked in anyway.
    Removes ** bold markers and leading/trailing whitespace.
    """
    cleaned = []
    for b in bullets:
        # Remove **text** bold markers
        b = re.sub(r'\*\*(.+?)\*\*', r'\1', b)
        # Remove any remaining asterisks
        b = b.replace('*', '')
        # Clean up extra whitespace
        b = b.strip()
        cleaned.append(b)
    return cleaned


def _make_fallback(product: dict) -> dict:
    """
    If the LLM fails completely, return a safe minimal listing.
    Flagged with _fallback: True so QA knows to flag it for human review.
    """
    return {
        "supplier_sku": product['supplier_sku'],
        "title": product['name'][:70],
        "bullets": [
            f"Brand — {product['brand']}",
            f"Category — {product['category']}",
            f"Description — {product['description'][:80]}",
            "Availability — in stock and ready to ship",
            "Quality — backed by supplier guarantee"
        ],
        "description": product['description'],
        "tags": [product['category'].lower(), product['brand'].lower()],
        "seo_title": product['name'][:60],
        "seo_description": product['description'][:160],
        "_fallback": True
    }


def run(selected_products: list[dict], llm: LLMProvider) -> list[dict]:
    """
    Generate a Shopify listing for each selected product using the LLM.
    Cleans bullet points after generation to remove any markdown artifacts.
    """
    listings = []
    total = len(selected_products)

    for i, product in enumerate(selected_products, 1):
        sku = product['supplier_sku']
        print(f"  [Listing] Generating listing {i}/{total}: {sku} — {product['name']}")

        prompt = LISTING_TEMPLATE.format(**product)
        result = llm.complete_json(prompt, system=SYSTEM_PROMPT)

        if not result or 'title' not in result:
            print(f"  [Listing] WARNING: LLM failed for {sku}, using fallback.")
            result = _make_fallback(product)
        else:
            result['supplier_sku'] = sku
            result['_fallback'] = False
            # FIX: Always clean bullets after generation to strip any ** markdown
            if 'bullets' in result and isinstance(result['bullets'], list):
                result['bullets'] = _clean_bullets(result['bullets'])

        listings.append(result)

    print(f"  [Listing] Generated {len(listings)} listings.")
    return listings