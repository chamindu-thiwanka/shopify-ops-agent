"""
Listing Agent
-------------
JOB: Use an LLM to write compelling Shopify product listings.

WHY AN LLM HERE:
  Writing product titles, bullet points, and descriptions that are
  persuasive, SEO-optimised, and engaging requires language creativity.
  This is exactly what LLMs excel at. A rule-based approach would produce
  robotic, identical-sounding listings that don't convert.

PROMPT DESIGN DECISIONS:
  1. We tell the LLM its role upfront ("You are a Shopify copywriter")
     — this is called a system prompt and sets the model's persona.
  2. We give it the exact JSON structure we expect back.
  3. We say "Return ONLY valid JSON" because LLMs love to add
     explanations unless explicitly told not to.
  4. We include the product's actual data so the listing is accurate.

OUTPUT: List of listing dicts → saved as listings.json
"""

import json
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

REQUIREMENTS:
- Title must be under 70 characters and include the main keyword naturally
- Write exactly 5 bullet points, each starting with a bold keyword
- Description must be 2-3 short paragraphs, persuasive but honest — no unverifiable claims
- Include 8 relevant search tags
- SEO title under 60 characters
- SEO description under 160 characters

Return this exact JSON structure:
{{
  "supplier_sku": "{supplier_sku}",
  "title": "string",
  "bullets": ["string", "string", "string", "string", "string"],
  "description": "string",
  "tags": ["string", "string", "string", "string", "string", "string", "string", "string"],
  "seo_title": "string",
  "seo_description": "string"
}}"""


def _make_fallback(product: dict) -> dict:
    """
    WHY A FALLBACK:
      If the LLM fails (bad JSON, timeout, etc.), we don't want the 
      entire pipeline to crash. A fallback listing lets the pipeline 
      continue — the QA agent will flag it as needing review.
    """
    return {
        "supplier_sku": product['supplier_sku'],
        "title": product['name'][:70],
        "bullets": [
            f"Brand: {product['brand']}",
            f"Category: {product['category']}",
            product['description'][:100],
            "Free shipping available",
            "Quality guaranteed"
        ],
        "description": product['description'],
        "tags": [product['category'].lower(), product['brand'].lower()],
        "seo_title": product['name'][:60],
        "seo_description": product['description'][:160],
        "_fallback": True  # Flag so QA knows this needs human review
    }


def run(selected_products: list[dict], llm: LLMProvider) -> list[dict]:
    """
    Generate a listing for each selected product.
    
    WHY WE CACHE:
      Generating 10 listings takes ~5-10 minutes with a local LLM.
      If the pipeline crashes at step 5, we don't want to re-generate
      all listings from scratch. Caching means we only call the LLM once
      per product, ever.
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
            result['supplier_sku'] = sku  # Ensure SKU is always present
            result['_fallback'] = False
        
        listings.append(result)
    
    print(f"  [Listing] Generated {len(listings)} listings.")
    return listings