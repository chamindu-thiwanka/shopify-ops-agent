
"""
Order Routing Agent
-------------------
JOB: For every incoming order, decide what to do and write a customer email.

THREE DECISIONS:
  1. FULFIL    — product is in our selected 10 and stock is sufficient
  2. BACKORDER — product is in our selected 10 but stock is too low
  3. SUBSTITUTE — product is not in our selected 10 (not listed, out of stock,
                  or discontinued) — offer a similar product

CHANGE LOG:
  - find_substitute now returns a tuple: (product, reason_string)
    so the note field clearly explains WHY that substitute was chosen
  - Category matching logic improved with clear fallback explanation
  - SKUs that don't exist in catalog at all now handled with specific message
  - run() updated to unpack the tuple correctly
"""

import pandas as pd


def find_substitute(
    original_sku: str,
    full_catalog_path: str,
    selected_products: list[dict]
) -> tuple[dict | None, str]:
    """
    Find the best substitute from our selected 10 products.

    Strategy:
      1. Look up the original SKU in the full catalog to get its category
      2. Find selected products in the same category (best semantic match)
      3. Among those, pick the one with the most stock (lowest backorder risk)
      4. If no same-category match, fall back to highest-stock product overall

    Returns:
      (substitute_product_dict, reason_string)
      The reason string appears in the note field of order_actions.json
    """
    try:
        catalog = pd.read_csv(full_catalog_path)
        original_rows = catalog[catalog['supplier_sku'] == original_sku]

        if original_rows.empty:
            # SKU doesn't exist in catalog at all (e.g. SKU099 in our test data)
            best = max(selected_products, key=lambda p: p['stock']) if selected_products else None
            reason = f"SKU {original_sku} not found in catalog — offering highest-stock alternative"
            return best, reason

        original_category = original_rows.iloc[0]['category']
        original_name = original_rows.iloc[0]['name']

        # Try to find a same-category product from our selected 10
        same_category = [
            p for p in selected_products
            if p.get('category') == original_category
        ]

        if same_category:
            best = max(same_category, key=lambda p: p['stock'])
            reason = (
                f"Same category ({original_category}) substitute for "
                f"'{original_name}' — best available stock"
            )
            return best, reason

        # No same-category match available — use highest stock product overall
        best = max(selected_products, key=lambda p: p['stock']) if selected_products else None
        reason = (
            f"No {original_category} products in active listings — "
            f"offering highest-stock alternative"
        )
        return best, reason

    except Exception as e:
        # If anything goes wrong reading the catalog, return first available product
        best = selected_products[0] if selected_products else None
        return best, f"Substitute lookup error ({str(e)[:50]}) — offering default"


def write_email(action: str, order: dict, substitute: dict = None) -> str:
    """
    Generate a customer-facing email based on the routing decision.
    In the Shopify integration phase, these would be sent via an email API.
    """
    order_id = order['order_id']
    sku = order['sku']

    if action == 'fulfil':
        return (
            f"Dear Customer,\n\n"
            f"Great news! Your order {order_id} for item {sku} has been confirmed "
            f"and is being processed. You can expect delivery within 3-7 business days.\n\n"
            f"Thank you for shopping with us!\n\nBest regards,\nOps Team"
        )
    elif action == 'backorder':
        return (
            f"Dear Customer,\n\n"
            f"Thank you for your order {order_id}. We currently have limited stock "
            f"for item {sku}. Your order is on backorder and will ship as soon as "
            f"new stock arrives (estimated 7-14 business days).\n\n"
            f"We apologise for any inconvenience.\n\nBest regards,\nOps Team"
        )
    elif action == 'substitute':
        sub_name = substitute['name'] if substitute else "a similar product"
        sub_sku = substitute['supplier_sku'] if substitute else "N/A"
        return (
            f"Dear Customer,\n\n"
            f"Regarding your order {order_id}: unfortunately item {sku} is currently "
            f"unavailable. We'd like to offer you {sub_name} ({sub_sku}) as an "
            f"equivalent alternative at the same price point.\n\n"
            f"Please reply to confirm or cancel. No charge until you confirm.\n\n"
            f"Best regards,\nOps Team"
        )
    return ""


def run(
    orders_path: str,
    catalog_path: str,
    selected_products: list[dict],
    stock_data: list[dict]
) -> list[dict]:
    """
    Route every order in orders.csv to one of three actions.
    Saves result to order_actions.json via the manager.
    """
    orders = pd.read_csv(orders_path).to_dict(orient='records')

    # Build fast lookup structures
    selected_skus = {p['supplier_sku'] for p in selected_products}
    stock_map = {s['supplier_sku']: s['available_stock'] for s in stock_data}

    actions = []

    for order in orders:
        sku = order['sku']
        qty = int(order['quantity'])
        substitute = None

        if sku not in selected_skus:
            # Product not in our active listings — find substitute
            action = 'substitute'
            # FIX: find_substitute now returns (product, reason) tuple
            substitute, sub_reason = find_substitute(sku, catalog_path, selected_products)
            sub_sku = substitute['supplier_sku'] if substitute else 'none found'
            note = f"{sub_reason}. Substitute: {sub_sku}"

        elif stock_map.get(sku, 0) < qty:
            # Product listed but not enough stock for this order quantity
            action = 'backorder'
            substitute = None
            note = f"Ordered {qty}, only {stock_map.get(sku, 0)} available."

        else:
            # Product listed and stock sufficient — fulfil normally
            action = 'fulfil'
            substitute = None
            note = f"Stock OK ({stock_map.get(sku, 0)} available, {qty} ordered)."

        actions.append({
            'order_id': order['order_id'],
            'sku': sku,
            'quantity': qty,
            'customer_country': order['customer_country'],
            'action': action,
            'note': note,
            'customer_email': write_email(action, order, substitute)
        })
        print(f"  [Orders] {order['order_id']}: {sku} → {action.upper()}")

    return actions