"""
Product Sourcing Agent
----------------------
JOB: Read the supplier catalog and pick the 10 best products to sell.

WHY NO LLM HERE:
  The selection criteria are completely objective and mathematical:
    - stock >= 10 (factual check)
    - margin >= 25% (math calculation)
  
  Using an LLM for pure math is wasteful, slow, and introduces errors.
  LLMs are for tasks that require language understanding or creativity.
  Rule of thumb: if you can write the logic as an if-statement, don't use an LLM.

OUTPUT: List of product dicts → saved as selection.json
"""

import pandas as pd
import math


def calculate_min_price(cost_price: float, shipping_cost: float) -> float:
    """
    Find the minimum selling price that achieves exactly 25% margin in AU.
    
    WHY THIS FORMULA:
      When you sell something on Shopify in Australia, you don't keep
      the full selling price. Costs that come out of it:
        1. Platform fee: Shopify takes 2.9% of the price + $0.30 flat
        2. GST (tax): Australian law requires 10% of the price goes to govt
        3. Cost of the product itself + shipping to customer
      
      After all that, you want to keep at least 25% of the price as profit.
      
    THE ALGEBRA (so you understand it, not just copy it):
      Let P = sell price
      Platform fee = 0.029 * P + 0.30
      GST = 0.10 * P
      Total cost = cost_price + shipping + platform_fee + GST
                 = cost_price + shipping + 0.029P + 0.30 + 0.10P
      
      Margin = (P - total_cost) / P >= 0.25
      P - total_cost >= 0.25P
      P - (cost_price + shipping + 0.029P + 0.30 + 0.10P) >= 0.25P
      P - 0.129P - (cost_price + shipping + 0.30) >= 0.25P
      0.871P - 0.25P >= cost_price + shipping + 0.30
      0.621P >= cost_price + shipping + 0.30
      P >= (cost_price + shipping + 0.30) / 0.621
      
    Then round UP to nearest $0.50 (so we never accidentally go below 25%).
    """
    fixed_costs = cost_price + shipping_cost + 0.30  # product + shipping + Shopify flat fee
    denominator = 1 - 0.029 - 0.10 - 0.25           # 0.621 for AU
    min_price = fixed_costs / denominator
    
    # Round up to nearest $0.50 using ceiling math
    # e.g. $21.32 → $21.50, $21.51 → $22.00
    return math.ceil(min_price * 2) / 2


def calculate_actual_margin(sell_price: float, cost_price: float, shipping_cost: float) -> float:
    """Calculate the real margin percentage at a given sell price (AU)."""
    platform_fee = 0.029 * sell_price + 0.30
    gst = 0.10 * sell_price
    total_cost = cost_price + shipping_cost + platform_fee + gst
    return round(((sell_price - total_cost) / sell_price) * 100, 2)


def run(catalog_path: str) -> list[dict]:
    """
    Main function — reads catalog, filters, ranks, returns top 10.
    
    SCORING LOGIC:
      We score each product by a combination of:
        - Stock level (higher stock = safer to list, less risk of backorders)
        - Absolute margin in dollars (a $5 margin on a $10 item is better
          than $5 margin on a $100 item percentage-wise but the same dollars)
      
      This is a simple heuristic. In a real business you'd also consider
      sell-through rate, competition, and seasonality.
    """
    print("  [Sourcing] Reading catalog...")
    df = pd.read_csv(catalog_path)
    total_products = len(df)
    
    # Step 1: Filter out products with insufficient stock
    df_filtered = df[df['stock'] >= 10].copy()
    filtered_by_stock = total_products - len(df_filtered)
    print(f"  [Sourcing] {filtered_by_stock} products removed (stock < 10). {len(df_filtered)} remain.")
    
    # Step 2: Calculate minimum viable price and verify 25% margin is achievable
    df_filtered['min_sell_price'] = df_filtered.apply(
        lambda row: calculate_min_price(row['cost_price'], row['shipping_cost']),
        axis=1
    )
    df_filtered['margin_at_min_price'] = df_filtered.apply(
        lambda row: calculate_actual_margin(
            row['min_sell_price'], row['cost_price'], row['shipping_cost']
        ),
        axis=1
    )
    
    # Filter: only keep products where 25% margin is achievable
    df_filtered = df_filtered[df_filtered['margin_at_min_price'] >= 25.0]
    print(f"  [Sourcing] {len(df_filtered)} products pass the 25% margin requirement.")
    
    # Step 3: Score and rank products
    # Normalise stock (0-1 scale) and dollar margin, then combine
    max_stock = df_filtered['stock'].max()
    df_filtered['dollar_margin'] = df_filtered['min_sell_price'] - df_filtered['cost_price'] - df_filtered['shipping_cost']
    df_filtered['stock_score'] = df_filtered['stock'] / max_stock
    df_filtered['margin_score'] = df_filtered['dollar_margin'] / df_filtered['dollar_margin'].max()
    df_filtered['composite_score'] = (df_filtered['stock_score'] * 0.4) + (df_filtered['margin_score'] * 0.6)
    
    # Step 4: Pick top 10
    top10 = df_filtered.nlargest(10, 'composite_score')
    
    result = top10.to_dict(orient='records')
    print(f"  [Sourcing] Selected {len(result)} products.")
    return result