"""
QA Agent
--------
JOB: Review each listing for dishonest or unverifiable claims.

WHY A SECOND LLM MODEL/MODE:
  QA is a different cognitive task from copywriting.
  The Listing Agent thinks creatively. The QA Agent thinks critically.
  Using a different model/mode gives genuinely independent review.

CHANGE LOG v1:
  - Shortened prompt — qwen3 was timing out on long prompts
  - Added empty response guard
  - Added think-block stripping
  - Fixed loop logging

CHANGE LOG v2:
  - FIX: Added _flatten_issues() — qwen3 was returning issues as objects
    [{"issue": "text", "description": "reason"}] instead of plain strings ["text"]
    This caused SKU009 and SKU021 to fail JSON validation even though the model
    actually did the QA correctly. Now we extract the text regardless of structure.

  - FIX: Supplier description now passed into prompt as verified source of truth.
    SKU028 was wrongly flagged for "900DPI claim is unverified" and "Micro SD slot
    not confirmed" — both specs come directly from the supplier description.
    Now the prompt tells the model: if it's in the supplier description, it's verified.
    Only flag claims the listing ADDED beyond what the supplier already stated.
"""

import re
from app.llm.provider import LLMProvider

SYSTEM_PROMPT = """You are a strict QA reviewer for e-commerce product listings.
Find over-claims, false specs, unverifiable superlatives, health claims without proof.
Return ONLY valid JSON. No markdown. No explanation. No preamble."""

# FIX v2: Supplier description included as verified source of truth.
# Prevents false positives where the model flags specs that came from the supplier.
QA_TEMPLATE = """Review this Shopify listing for SKU {supplier_sku}.

VERIFIED FACTS (from supplier — these are confirmed, do NOT flag them):
{supplier_description}

Title: {title}
Bullet points:
{bullets_formatted}

Only flag claims in the title or bullets that go BEYOND the verified facts above.
Do NOT flag specs that appear in the supplier description.

Check only for:
- Superlatives not supported by supplier ("world's best", "fastest ever")
- Specs the listing invented that the supplier did NOT mention
- Health/medical claims without evidence

Return ONLY this JSON — issues must be a flat list of plain strings, never objects:
{{"sku": "{supplier_sku}", "issues": ["plain string issue"], "severity": "ok", "suggested_fix": "none"}}

If no issues: {{"sku": "{supplier_sku}", "issues": [], "severity": "ok", "suggested_fix": "none"}}
severity options: "ok" | "minor" | "major" """


def _flatten_issues(issues: list) -> list[str]:
    """
    Normalise the issues list to always be a flat list of plain strings.

    WHY THIS IS NEEDED:
      qwen3 sometimes returns issues as objects instead of strings:
        WRONG: [{"issue": "30hr claim", "description": "unverifiable"}]
        RIGHT: ["30hr claim — unverifiable"]

      Both SKU009 and SKU021 failed validation because of this structure.
      Rather than discarding the QA result, we extract whatever text the
      model produced and convert it to a plain string. The QA work isn't lost.
    """
    flat = []
    for item in issues:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, dict):
            # Try common keys the model uses for issue text
            parts = []
            for key in ['issue', 'description', 'text', 'claim', 'detail', 'message', 'type']:
                val = item.get(key)
                if val and isinstance(val, str):
                    parts.append(val)
            if parts:
                flat.append(' — '.join(parts))
            else:
                # Last resort: join all string values
                flat.append(' '.join(str(v) for v in item.values() if v))
        else:
            flat.append(str(item))
    return [f for f in flat if f.strip()]  # Remove empty strings


def _make_parse_fallback(sku: str) -> dict:
    """Safe fallback when LLM returns completely unparseable output."""
    return {
        "sku": sku,
        "issues": ["QA parse failed — manual review needed"],
        "severity": "minor",
        "suggested_fix": "Re-run QA agent"
    }


def run(listings: list[dict], llm: LLMProvider, selected_products: list[dict] = None) -> list[dict]:
    """
    Review each listing for quality issues.

    Args:
        listings:          Output from the listing agent (listings.json)
        llm:               The QA LLM provider (second model)
        selected_products: Original catalog data — used to provide supplier
                           description as verified facts in the QA prompt
    """
    # Build SKU → supplier description lookup for the QA prompt
    description_map = {}
    if selected_products:
        for p in selected_products:
            description_map[p['supplier_sku']] = p.get('description', '')

    redlines = []
    total = len(listings)

    for i, listing in enumerate(listings, 1):
        sku = listing.get('supplier_sku', 'UNKNOWN')
        print(f"  [QA] Reviewing listing {i}/{total}: {sku}")

        # Fallback listings skip LLM — already flagged as broken
        if listing.get('_fallback'):
            redlines.append({
                "sku": sku,
                "issues": ["Fallback listing — needs human review"],
                "severity": "major",
                "suggested_fix": "Rewrite manually or re-run pipeline"
            })
            continue

        # Clean bullets of any stray markdown before sending to QA
        bullets = listing.get('bullets', [])
        clean_bullets = [
            re.sub(r'\*\*(.+?)\*\*', r'\1', b).replace('*', '').strip()
            for b in bullets
        ]
        bullets_formatted = "\n".join(f"- {b}" for b in clean_bullets)

        # FIX v2: Pass supplier description so QA knows what's already verified
        supplier_description = description_map.get(sku, 'Not available')

        prompt = QA_TEMPLATE.format(
            supplier_sku=sku,
            supplier_description=supplier_description,
            title=listing.get('title', ''),
            bullets_formatted=bullets_formatted,
        )

        raw = llm.complete(prompt, system=SYSTEM_PROMPT)

        # Guard: empty response (silent timeout)
        if not raw or not raw.strip():
            print(f"  [QA] WARNING: Empty response for {sku} — using fallback")
            redlines.append(_make_parse_fallback(sku))
            continue

        # Strip qwen3 think blocks before parsing
        cleaned = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        result = llm._parse_json_safely(cleaned)

        if not result or 'severity' not in result:
            print(f"  [QA] WARNING: Could not parse JSON for {sku} — using fallback")
            redlines.append(_make_parse_fallback(sku))
            continue

        # FIX v2: Flatten issues — converts object-style issues to plain strings
        # This is what prevents SKU009 and SKU021 from failing
        if 'issues' in result and isinstance(result['issues'], list):
            result['issues'] = _flatten_issues(result['issues'])

        result['sku'] = sku
        redlines.append(result)

    ok_count = sum(1 for r in redlines if r.get('severity') == 'ok')
    minor_count = sum(1 for r in redlines if r.get('severity') == 'minor')
    major_count = sum(1 for r in redlines if r.get('severity') == 'major')
    print(f"  [QA] Results: {ok_count} OK, {minor_count} minor, {major_count} major issues.")
    return redlines