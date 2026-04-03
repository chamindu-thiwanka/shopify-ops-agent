# """
# QA Agent
# --------
# JOB: Review each listing for dishonest or unverifiable claims.

# WHY A SECOND LLM (mistral):
#   QA is a different cognitive task from copywriting.
#   - The Listing Agent (llama3) thinks creatively: "How do I make this sound great?"
#   - The QA Agent (mistral) thinks critically: "What claims can't be proven?"
  
#   Using the same model for both would be like asking someone to proofread
#   their own work — they'll miss their own errors. Different models have
#   different training and tendencies, making the QA more genuinely independent.
  
#   This also demonstrates the multi-LLM requirement clearly.

# WHAT IT CATCHES:
#   - Superlatives with no basis: "world's best", "fastest ever"
#   - Fake specifications: "charges in 10 minutes" when supplier doesn't claim this
#   - Health claims: "proven to cure back pain"
#   - Misleading comparisons: "better than competitors"

# OUTPUT: listing_redlines.json
# """

# import json
# from app.llm.provider import LLMProvider

# SYSTEM_PROMPT = """You are a strict e-commerce QA reviewer. Your job is to find 
# over-claims, unverifiable superlatives, misleading statements, and false specifications 
# in product listings.

# Be specific about what the issue is and why it's problematic.
# CRITICAL: Return ONLY valid JSON. No markdown. No explanation."""

# QA_TEMPLATE = """Review this product listing for quality and honesty issues.

# LISTING TO REVIEW:
# SKU: {supplier_sku}
# Title: {title}
# Bullet points:
# {bullets_formatted}
# Description: {description}

# Check for:
# 1. Unverifiable superlatives ("best", "fastest", "world's #1")
# 2. False or exaggerated specifications
# 3. Health claims without evidence
# 4. Claims that contradict common sense

# Return this exact JSON:
# {{
#   "sku": "{supplier_sku}",
#   "issues": ["specific issue 1", "specific issue 2"],
#   "severity": "ok",
#   "suggested_fix": "brief fix suggestion or 'none'"
# }}

# Severity levels:
# - "ok": no issues found
# - "minor": small wording issues, easy to fix
# - "major": false claims that could mislead customers or violate consumer law

# If no issues, return: {{"sku": "{supplier_sku}", "issues": [], "severity": "ok", "suggested_fix": "none"}}"""


# def run(listings: list[dict], llm: LLMProvider) -> list[dict]:
#     redlines = []
#     total = len(listings)

#     for i, listing in enumerate(listings, 1):
#         sku = listing.get('supplier_sku', 'UNKNOWN')
#         print(f"  [QA] Reviewing listing {i}/{total}: {sku}")

#         # Format bullets for readability in the prompt
#         bullets = listing.get('bullets', [])
#         bullets_formatted = "\n".join(f"  - {b}" for b in bullets)

#         # Skip LLM for fallback listings — flag them directly
#         if listing.get('_fallback'):
#             redlines.append({
#                 "sku": sku,
#                 "issues": ["Listing was auto-generated fallback due to LLM failure — needs human review"],
#                 "severity": "major",
#                 "suggested_fix": "Rewrite listing manually or re-run pipeline"
#             })
#             continue

#         prompt = QA_TEMPLATE.format(
#             supplier_sku=sku,
#             title=listing.get('title', ''),
#             bullets_formatted=bullets_formatted,
#             description=listing.get('description', '')
#         )

#         result = llm.complete_json(prompt, system=SYSTEM_PROMPT)

#         if not result or 'severity' not in result:
#             result = {
#                 "sku": sku,
#                 "issues": ["QA parse failed — manual review needed"],
#                 "severity": "minor",
#                 "suggested_fix": "Re-run QA agent"
#             }

#         redlines.append(result)

#     ok_count = sum(1 for r in redlines if r.get('severity') == 'ok')
#     major_count = sum(1 for r in redlines if r.get('severity') == 'major')
#     print(f"  [QA] Results: {ok_count} OK, {major_count} major issues.")
#     return redlines

"""
QA Agent
--------
JOB: Review each listing for dishonest or unverifiable claims.
Uses a second LLM model/mode to act as an independent reviewer.
"""

import re
from app.llm.provider import LLMProvider

SYSTEM_PROMPT = """You are a strict QA reviewer for e-commerce product listings.
Find over-claims, false specs, unverifiable superlatives, health claims without proof.
Return ONLY valid JSON. No markdown. No explanation. No preamble."""

# Kept deliberately short — small models fail on long prompts
QA_TEMPLATE = """Review this listing for SKU {supplier_sku}.

Title: {title}
Bullets:
{bullets_formatted}

Find issues like: "world's best", unverifiable specs, health claims without proof.

Return ONLY this JSON:
{{"sku": "{supplier_sku}", "issues": [], "severity": "ok", "suggested_fix": "none"}}

If issues exist, fill the issues list and set severity to "minor" or "major"."""


def _make_parse_fallback(sku: str) -> dict:
    return {
        "sku": sku,
        "issues": ["QA parse failed — manual review needed"],
        "severity": "minor",
        "suggested_fix": "Re-run QA agent"
    }


def run(listings: list[dict], llm: LLMProvider) -> list[dict]:
    redlines = []
    total = len(listings)

    for i, listing in enumerate(listings, 1):
        sku = listing.get('supplier_sku', 'UNKNOWN')
        print(f"  [QA] Reviewing listing {i}/{total}: {sku}")

        # Fallback listings skip LLM — already flagged
        if listing.get('_fallback'):
            redlines.append({
                "sku": sku,
                "issues": ["Fallback listing — needs human review"],
                "severity": "major",
                "suggested_fix": "Rewrite manually or re-run pipeline"
            })
            continue

        bullets = listing.get('bullets', [])
        # Strip markdown bold markers (**text**) before sending to QA
        clean_bullets = [re.sub(r'\*\*(.+?)\*\*', r'\1', b) for b in bullets]
        bullets_formatted = "\n".join(f"- {b}" for b in clean_bullets)

        prompt = QA_TEMPLATE.format(
            supplier_sku=sku,
            title=listing.get('title', ''),
            bullets_formatted=bullets_formatted,
        )

        # Get raw response
        raw = llm.complete(prompt, system=SYSTEM_PROMPT)

        # Guard: empty response
        if not raw or not raw.strip():
            print(f"  [QA] WARNING: Empty response for {sku}")
            redlines.append(_make_parse_fallback(sku))
            continue

        # Strip think blocks (qwen3 reasoning mode)
        cleaned = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        # Try to parse JSON
        result = llm._parse_json_safely(cleaned)

        if not result or 'severity' not in result:
            print(f"  [QA] WARNING: Could not parse JSON for {sku}")
            redlines.append(_make_parse_fallback(sku))
            continue

        # Ensure sku field is always present
        result['sku'] = sku
        redlines.append(result)

    ok_count = sum(1 for r in redlines if r.get('severity') == 'ok')
    minor_count = sum(1 for r in redlines if r.get('severity') == 'minor')
    major_count = sum(1 for r in redlines if r.get('severity') == 'major')
    print(f"  [QA] Results: {ok_count} OK, {minor_count} minor, {major_count} major issues.")
    return redlines