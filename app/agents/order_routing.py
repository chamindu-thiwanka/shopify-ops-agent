"""
Order Routing Agent
-------------------
JOB: For every incoming order, decide what to do and write a customer email.

THREE POSSIBLE DECISIONS:
  1. FULFIL — product is selected and stock is sufficient → confirm order
  2. BACKORDER — product is selected but stock is too low → notify customer of delay
  3. SUBSTITUTE — product is not in our selected 10 (discontinued/out of stock/
     not listed) → offer a similar product from our catalog

WHY EMAILS HERE:
  In a real dropshipping operation, these emails would be sent via
  SendGrid or Mailchimp. Here we generate them as text so they're ready
  to be templated into a real email system. The extra credit version
  would actually send them.

WHY NO LLM:
  The decisions are rule-based (if stock >= qty → fulfil). The emails
  are templated — personalised with order data but not creatively written.
  Using an LLM for templated emails is unnecessary overhead.
"""

import pandas as pd


def find_substitute(
    original_sku: str,
    full_catalog_path: str,
    selected_products: list[dict]
) -> dict | None:
    """
    Find the most similar product from our selected 10 to substitute with.
    
    STRATEGY:
      1. Look up the original SKU's category in the full catalog
      2. Find products in our selected 10 that match that category
      3. Return the one with the highest stock (most available)
    """
    try:
        catalog = pd.read_csv(full_catalog_path)
        original = catalog[catalog['supplier_sku'] == original_sku]
        if original.empty:
            # SKU doesn't even exist in catalog
            return selected_products[0] if selected_products else None
        
        original_category = original.iloc[0]['category']
        
        # Find same-category products in our selected list
        same_category = [
            p for p in selected_products
            if p.get('category') == original_category and p['supplier_sku'] != original_sku
        ]
        
        if same_category:
            # Return the one with most stock
            return max(same_category, key=lambda p: p['stock'])
        
        # No same-category match — return highest stock product overall
        return max(selected_products, key=lambda p: p['stock']) if selected_products else None
    except Exception:
        return selected_products[0] if selected_products else None


def write_email(action: str, order: dict, substitute: dict = None) -> str:
    """Generate a customer-facing email based on the routing decision."""
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
    orders = pd.read_csv(orders_path).to_dict(orient='records')
    
    selected_skus = {p['supplier_sku'] for p in selected_products}
    stock_map = {s['supplier_sku']: s['available_stock'] for s in stock_data}

    actions = []

    for order in orders:
        sku = order['sku']
        qty = int(order['quantity'])
        substitute = None

        if sku not in selected_skus:
            action = 'substitute'
            substitute = find_substitute(sku, catalog_path, selected_products)
            note = f"SKU not in active listings. Substitute: {substitute['supplier_sku'] if substitute else 'none found'}"
        elif stock_map.get(sku, 0) < qty:
            action = 'backorder'
            note = f"Ordered {qty}, only {stock_map.get(sku, 0)} available."
        else:
            action = 'fulfil'
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