"""
Shopify Sync Module
-------------------
PURPOSE:
  Bridge between pipeline output data and the live Shopify store.
  Creates or updates products, then sets inventory levels correctly.

WHY A SEPARATE FILE:
  Agents are pure business logic — they work without Shopify.
  Isolating sync here means:
    1. Pipeline works without credentials (simulation mode)
    2. Only this file changes if Shopify's API changes
    3. Easy to swap platforms in future

HOW IT WORKS:
  1. Authenticate using the access token from .env
  2. For each product: check if it exists by SKU
       - Exists → UPDATE price, description, title
       - New    → CREATE full product
  3. Set inventory in two steps:
       a. connect to location (required before setting quantity)
       b. set the quantity

INVENTORY APPROACH:
  We use set_stock() which calls connect then set.
  For CREATE: inventory_item_id comes from POST response.
  For UPDATE: inventory_item_id comes from EXISTING product variant
              fetched BEFORE the PUT call. PUT responses are unreliable
              for this field — this was the root cause of the 0 stock bug.
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


class ShopifySync:

    def __init__(self):
        self.shop_url    = os.getenv("SHOPIFY_SHOP_URL", "").rstrip("/")
        self.token       = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        self.api_version = "2024-01"

        if not self.shop_url or not self.token:
            raise ValueError(
                "SHOPIFY_SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set "
                "in your .env file."
            )

        self.base_url = (
            f"https://{self.shop_url}/admin/api/{self.api_version}"
        )
        self.headers = {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json"
        }
        print(f"  [Shopify] Connected to: {self.shop_url}")

    # ── HTTP helpers ──────────────────────────────────────────────

    def _get(self, endpoint: str) -> dict:
        r = requests.get(
            f"{self.base_url}{endpoint}",
            headers=self.headers, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        r = requests.post(
            f"{self.base_url}{endpoint}",
            headers=self.headers, json=data, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def _put(self, endpoint: str, data: dict) -> dict:
        r = requests.put(
            f"{self.base_url}{endpoint}",
            headers=self.headers, json=data, timeout=30
        )
        r.raise_for_status()
        return r.json()

    # ── Store lookup helpers ──────────────────────────────────────

    def get_location_id(self) -> str:
        """
        Get the default inventory location ID.

        WHY NEEDED: Shopify tracks stock per location. Development stores
        have one default location. We need its numeric ID for inventory calls.
        """
        data      = self._get("/locations.json")
        locations = data.get("locations", [])
        if not locations:
            raise ValueError("No locations found in your Shopify store.")
        location_id = str(locations[0]["id"])
        print(f"  [Shopify] Using location ID: {location_id}")
        return location_id

    def find_existing_product(self, sku: str) -> dict | None:
        """
        Find a product in Shopify by SKU.

        WHY: Prevents duplicates on re-runs. If found, we update.
        If not found, we create. Shopify stores SKUs inside variants.
        """
        data = self._get("/products.json?limit=250")
        for product in data.get("products", []):
            for variant in product.get("variants", []):
                if variant.get("sku") == sku:
                    return product
        return None

    def get_variant_inventory_item_id(self, product: dict) -> str | None:
        """
        Extract inventory_item_id from the first variant of a product.

        WHY THIS MATTERS:
          Every product variant has an inventory_item_id.
          For CREATE: read from API response after creation.
          For UPDATE: MUST read from existing product BEFORE PUT.
          PUT response is unreliable for this field.
          Reading it before PUT fixes the 0 stock bug.
        """
        variants = product.get("variants", [])
        if variants:
            iid = variants[0].get("inventory_item_id")
            if iid:
                return str(iid)
        return None

    # ── Product payload builder ───────────────────────────────────

    def build_payload(
        self, listing: dict, price_data: dict, product: dict
    ) -> dict:
        """
        Build the product JSON that Shopify's API accepts.

        KEY FIELDS:
          body_html    → HTML description shown in storefront
          variants     → price + SKU (one per product)
          images       → Shopify fetches from the URL
          tags         → comma-separated string
          status       → "draft" = not visible until published
        """
        bullets_html = "<ul>" + "".join(
            f"<li>{b}</li>" for b in listing.get("bullets", [])
        ) + "</ul>"

        return {
            "product": {
                "title":        listing.get("title", product["name"]),
                "body_html":    bullets_html + f"<p>{listing.get('description', '')}</p>",
                "vendor":       product.get("brand", ""),
                "product_type": product.get("category", ""),
                "tags":         ", ".join(listing.get("tags", [])),
                "status":       "draft",
                "variants": [{
                    "sku":                  product["supplier_sku"],
                    "price":                str(price_data["sell_price_au"]),
                    "inventory_management": "shopify",
                    "inventory_policy":     "deny",
                    "weight":               product.get("weight_kg", 0),
                    "weight_unit":          "kg",
                    "fulfillment_service":  "manual"
                }],
                "images": (
                    [{"src": product["image_url"]}]
                    if product.get("image_url") else []
                ),
                "metafields": [
                    {
                        "namespace": "ops_agent",
                        "key":       "seo_title",
                        "value":     listing.get("seo_title", ""),
                        "type":      "single_line_text_field"
                    },
                    {
                        "namespace": "ops_agent",
                        "key":       "seo_description",
                        "value":     listing.get("seo_description", ""),
                        "type":      "single_line_text_field"
                    }
                ]
            }
        }

    # ── Inventory management ──────────────────────────────────────

    def set_stock(
        self,
        inventory_item_id: str,
        location_id: str,
        quantity: int
    ):
        """
        Set the stock level for a product at the store location.

        TWO-STEP PROCESS:
          Step 1 — connect: tells Shopify this item is at this location.
                   Safe to call repeatedly (ignored if already connected).
          Step 2 — set: writes the actual quantity.

        WHY TWO STEPS:
          Shopify separates "where a product is stocked" from
          "how many are available". You must connect first, then set.
          Without connect, set returns 422 or silently ignores the request.
        """
        iid = int(inventory_item_id)
        lid = int(location_id)

        # Step 1: connect — safe even if already connected
        try:
            self._post("/inventory_levels/connect.json", {
                "inventory_item_id":     iid,
                "location_id":           lid,
                "relocate_if_necessary": False
            })
        except requests.exceptions.HTTPError:
            pass  # 422 = already connected — fine, continue to set

        # Step 2: set the actual quantity
        self._post("/inventory_levels/set.json", {
            "inventory_item_id": iid,
            "location_id":       lid,
            "available":         quantity
        })
        print(f"    [Shopify] Stock set to {quantity} units")

    # ── Main sync logic ───────────────────────────────────────────

    def sync_product(
        self,
        listing: dict,
        price_data: dict,
        stock_data: dict,
        product: dict,
        location_id: str
    ) -> str:
        """
        Create or update one product, then set its stock level.

        Returns: "created" | "updated" | "failed"
        """
        sku = product["supplier_sku"]

        try:
            existing = self.find_existing_product(sku)
            payload  = self.build_payload(listing, price_data, product)

            if existing:
                # UPDATE — read iid from existing BEFORE PUT call
                iid    = self.get_variant_inventory_item_id(existing)
                self._put(f"/products/{existing['id']}.json", payload)
                action = "updated"

            else:
                # CREATE — read iid from POST response
                response = self._post("/products.json", payload)
                created  = response.get("product", {})
                iid      = self.get_variant_inventory_item_id(created)
                action   = "created"

            # Set inventory — same for both create and update
            quantity = int(stock_data.get("available_stock", 0))
            if iid:
                self.set_stock(iid, location_id, quantity)
            else:
                print(f"    [Shopify] WARNING: No inventory_item_id for {sku}")

            print(f"  [Shopify] {sku}: {action} (stock: {quantity})")
            time.sleep(0.6)  # Shopify rate limit: 2 req/sec
            return action

        except requests.exceptions.HTTPError as e:
            print(
                f"  [Shopify] ERROR {sku}: "
                f"{e.response.status_code} — {e.response.text[:300]}"
            )
            return "failed"
        except Exception as e:
            print(f"  [Shopify] ERROR {sku}: {str(e)[:300]}")
            return "failed"


# ── Module entry point ────────────────────────────────────────────

def run(
    selected_products: list[dict],
    listings: list[dict],
    prices: list[dict],
    stocks: list[dict]
) -> dict:
    """
    Sync all selected products to Shopify.

    Called by manager.py after all agents have run.
    Returns a result dict that appears in daily_report.md.
    """
    print("\n  [Shopify] Starting product sync...")

    try:
        client      = ShopifySync()
        location_id = client.get_location_id()
    except Exception as e:
        print(f"  [Shopify] SETUP FAILED: {e}")
        print("  [Shopify] Skipping sync — check your .env credentials.")
        return {"created": 0, "updated": 0, "failed": 0, "skipped": True}

    listing_map = {l["supplier_sku"]: l for l in listings}
    price_map   = {p["supplier_sku"]: p for p in prices}
    stock_map   = {s["supplier_sku"]: s for s in stocks}

    results = {"created": 0, "updated": 0, "failed": 0, "skipped": False}
    total   = len(selected_products)

    for i, product in enumerate(selected_products, 1):
        sku = product["supplier_sku"]
        print(f"  [Shopify] Syncing {i}/{total}: {sku} — {product['name']}")

        listing    = listing_map.get(sku, {})
        price_data = price_map.get(sku, {})
        stock_data = stock_map.get(sku, {})

        if not listing or not price_data:
            print(f"  [Shopify] WARNING: Missing data for {sku} — skipping")
            results["failed"] += 1
            continue

        action = client.sync_product(
            listing, price_data, stock_data, product, location_id
        )
        results[action] = results.get(action, 0) + 1

    print(
        f"\n  [Shopify] Sync complete: "
        f"{results['created']} created, "
        f"{results['updated']} updated, "
        f"{results['failed']} failed."
    )
    return results