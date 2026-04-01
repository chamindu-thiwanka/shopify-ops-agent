"""
Pricing & Stock Agent
---------------------
JOB: Calculate the exact sell price for each product and output two CSVs.

WHY DETERMINISTIC (no LLM):
  Pricing is math. There is one correct answer for any given cost_price
  and shipping_cost combination. An LLM could never be trusted to calculate
  this accurately — it might round differently, use the wrong formula,
  or hallucinate. Always use deterministic code for financial calculations.

WHY TWO SEPARATE CSVs:
  price_update.csv → would be uploaded to Shopify to update product prices
  stock_update.csv → would be synced to Shopify's inventory system
  
  In the extra credit version, these CSVs become direct Shopify API calls.
  Keeping them separate mirrors how real Shopify integrations work.

OUTPUT: price_update.csv, stock_update.csv (written directly), also returns data
"""

import pandas as pd
import math
import os


def calculate_price_au(cost_price: float, shipping_cost: float) -> float:
    """AU pricing with GST. Same formula as sourcing agent."""
    fixed = cost_price + shipping_cost + 0.30
    return math.ceil((fixed / 0.621) * 2) / 2


def calculate_price_non_au(cost_price: float, shipping_cost: float) -> float:
    """Non-AU pricing without GST."""
    fixed = cost_price + shipping_cost + 0.30
    return math.ceil((fixed / 0.721) * 2) / 2


def calculate_margin(sell_price: float, cost_price: float, shipping_cost: float, is_au: bool = True) -> float:
    """Calculate real margin percentage after all fees."""
    platform_fee = 0.029 * sell_price + 0.30
    gst = 0.10 * sell_price if is_au else 0
    total_cost = cost_price + shipping_cost + platform_fee + gst
    return round(((sell_price - total_cost) / sell_price) * 100, 2)


def run(selected_products: list[dict], out_dir: str) -> tuple[list[dict], list[dict]]:
    price_rows = []
    stock_rows = []

    for product in selected_products:
        cost = product['cost_price']
        shipping = product['shipping_cost']
        
        # Calculate AU price (our primary market)
        sell_price_au = calculate_price_au(cost, shipping)
        margin_au = calculate_margin(sell_price_au, cost, shipping, is_au=True)
        
        # Also calculate non-AU price for reference
        sell_price_world = calculate_price_non_au(cost, shipping)

        price_rows.append({
            'supplier_sku': product['supplier_sku'],
            'name': product['name'],
            'cost_price': cost,
            'shipping_cost': shipping,
            'sell_price_au': sell_price_au,
            'sell_price_world': sell_price_world,
            'margin_pct_au': margin_au,
            'lead_days': product['supplier_lead_days']
        })

        stock_rows.append({
            'supplier_sku': product['supplier_sku'],
            'name': product['name'],
            'available_stock': product['stock'],
            'reorder_threshold': 15,
            'needs_reorder': product['stock'] < 15,
            'days_of_supply': product['stock']  # simplified: assume 1 sale/day
        })

    # Write CSVs
    pd.DataFrame(price_rows).to_csv(f"{out_dir}/price_update.csv", index=False)
    pd.DataFrame(stock_rows).to_csv(f"{out_dir}/stock_update.csv", index=False)
    print(f"  [Pricing] price_update.csv and stock_update.csv written.")

    return price_rows, stock_rows