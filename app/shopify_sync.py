"""
Shopify Sync Module
-------------------
PURPOSE:
  This module is the bridge between your pipeline's output data and
  your real Shopify store. It takes the listings, prices, and stock
  levels that your agents already produced and pushes them live.

WHY A SEPARATE FILE (not added to existing agents):
  The existing agents are pure business logic — they work with or
  without Shopify. Keeping Shopify as a separate module means:
    1. You can run the pipeline locally without any Shopify credentials
    2. If Shopify's API changes, you only update this one file
    3. The simulation still works perfectly if Shopify is down
    4. It's easy to swap Shopify for another platform later

HOW IT WORKS:
  1. Authenticate with your store using the access token from .env
  2. For each listing: check if the product already exists (by SKU)
     - If it does: UPDATE it (price, stock, description)
     - If it doesn't: CREATE it (full product with all details)
  3. After creating/updating: set the inventory level
  4. Log every action so you can see exactly what happened

SHOPIFY API BASICS:
  Shopify's REST Admin API works like this:
  - Products:  POST /admin/api/2024-01/products.json      (create)
               PUT  /admin/api/2024-01/products/{id}.json (update)
  - Inventory: POST /admin/api/2024-01/inventory_levels/set.json (set stock)
  
  Every request needs the X-Shopify-Access-Token header.
  Rate limit: 2 requests/second on development stores (we add delays).
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


class ShopifySync:
    """
    Handles all communication with the Shopify Admin REST API.
    
    WHY A CLASS:
      We need to store the shop URL and token once, then reuse them
      across many API calls. A class is cleaner than passing credentials
      to every function individually.
    """

    def __init__(self):
        self.shop_url = os.getenv("SHOPIFY_SHOP_URL", "").rstrip("/")
        self.token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        self.api_version = "2024-01"

        if not self.shop_url or not self.token:
            raise ValueError(
                "SHOPIFY_SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set in your .env file.\n"
                "See README for setup instructions."
            )

        self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"
        self.headers = {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json"
        }
        print(f"  [Shopify] Connected to: {self.shop_url}")

    def _get(self, endpoint: str) -> dict:
        """
        Make a GET request to the Shopify API.
        Used for reading existing products and inventory locations.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        """
        Make a POST request — used for creating products and setting inventory.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, headers=self.headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def _put(self, endpoint: str, data: dict) -> dict:
        """
        Make a PUT request — used for updating existing products.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.put(url, headers=self.headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_location_id(self) -> str:
        """
        Get the inventory location ID for your store.

        WHY WE NEED THIS:
          Shopify tracks inventory per physical location (warehouse, store, etc).
          Development stores have one default location. We need its ID to tell
          Shopify which location's inventory to update when we set stock levels.
          Without this, the inventory update call fails.
        """
        data = self._get("/locations.json")
        locations = data.get("locations", [])
        if not locations:
            raise ValueError("No locations found in your Shopify store.")
        location_id = str(locations[0]["id"])
        print(f"  [Shopify] Using location ID: {location_id}")
        return location_id

    def find_existing_product(self, sku: str) -> dict | None:
        """
        Search for an existing product by SKU in your Shopify store.

        WHY WE CHECK FIRST:
          If you run the pipeline twice, you don't want 20 duplicate products
          in your store. By searching for the SKU first, we can UPDATE an
          existing product instead of creating a second copy.

          Shopify stores SKUs on product variants. We search all products
          and check each variant's SKU field.
        """
        data = self._get(f"/products.json?limit=250")
        products = data.get("products", [])

        for product in products:
            for variant in product.get("variants", []):
                if variant.get("sku") == sku:
                    return product

        return None  # Not found — will create new

    def build_product_payload(
        self,
        listing: dict,
        price_data: dict,
        stock_data: dict,
        product: dict
    ) -> dict:
        """
        Build the JSON payload that Shopify's API expects for a product.

        WHY THIS STRUCTURE:
          Shopify has a specific shape for product data. Understanding it:
          - body_html: the description (Shopify renders HTML, so we use <p> tags)
          - variants: a product can have multiple variants (sizes, colours).
            We have one variant per product — we set price and SKU here.
          - images: Shopify downloads the image from the URL you provide.
          - tags: comma-separated string (not a list)
        """
        # Convert bullet points to HTML list for Shopify's description field
        bullets_html = "<ul>" + "".join(
            f"<li>{b}</li>" for b in listing.get("bullets", [])
        ) + "</ul>"

        # Full description: bullets + paragraph text
        full_description = (
            bullets_html +
            f"<p>{listing.get('description', '')}</p>"
        )

        payload = {
            "product": {
                "title": listing.get("title", product["name"]),
                "body_html": full_description,
                "vendor": product.get("brand", ""),
                "product_type": product.get("category", ""),
                "tags": ", ".join(listing.get("tags", [])),
                "status": "draft",   # draft = not visible to customers yet
                                     # Change to "active" to make it live
                "variants": [
                    {
                        "sku": product["supplier_sku"],
                        "price": str(price_data["sell_price_au"]),
                        "inventory_management": "shopify",
                        # inventory_management = "shopify" tells Shopify to
                        # track this product's stock automatically
                        "inventory_policy": "deny",
                        # "deny" = don't allow purchase when out of stock
                        # (alternative: "continue" = allow backorders)
                        "weight": product.get("weight_kg", 0),
                        "weight_unit": "kg",
                        "fulfillment_service": "manual"
                    }
                ],
                "images": [
                    {"src": product.get("image_url", "")}
                ] if product.get("image_url") else [],
                "metafields": [
                    {
                        "namespace": "ops_agent",
                        "key": "seo_title",
                        "value": listing.get("seo_title", ""),
                        "type": "single_line_text_field"
                    },
                    {
                        "namespace": "ops_agent",
                        "key": "seo_description",
                        "value": listing.get("seo_description", ""),
                        "type": "single_line_text_field"
                    }
                ]
            }
        }
        return payload

    def set_inventory(self, inventory_item_id: str, location_id: str, quantity: int):
        """
        Set the stock level for a product variant at your store location.

        WHY A SEPARATE CALL:
          In Shopify, inventory is set separately from product creation.
          First you create the product (which creates an inventory_item_id),
          then you call this endpoint to set how many units are available.
          This mirrors how real warehouses work — the product exists
          independently of how many you have in stock.
        """
        payload = {
            "location_id": int(location_id),
            "inventory_item_id": int(inventory_item_id),
            "available": quantity
        }
        self._post("/inventory_levels/set.json", payload)

    def sync_product(
        self,
        listing: dict,
        price_data: dict,
        stock_data: dict,
        product: dict,
        location_id: str
    ) -> str:
        """
        Create or update a single product in Shopify.

        Returns:
          "created" — new product was added to your store
          "updated" — existing product was updated
          "failed"  — something went wrong (logged, pipeline continues)

        WHY CREATE-OR-UPDATE PATTERN:
          Running the pipeline multiple times should be safe.
          First run: creates 10 products.
          Second run: updates the same 10 products (price changes, new listings).
          Without this pattern, you'd get 10 new duplicate products every run.
        """
        sku = product["supplier_sku"]

        try:
            # Check if product already exists
            existing = self.find_existing_product(sku)
            payload = self.build_product_payload(listing, price_data, stock_data, product)

            if existing:
                # UPDATE existing product
                product_id = existing["id"]
                result = self._put(f"/products/{product_id}.json", payload)
                action = "updated"
            else:
                # CREATE new product
                result = self._post("/products.json", payload)
                action = "created"

            # Get the inventory item ID from the first variant
            shopify_product = result.get("product", {})
            variants = shopify_product.get("variants", [])

            if variants:
                inventory_item_id = variants[0].get("inventory_item_id")
                if inventory_item_id:
                    quantity = stock_data.get("available_stock", 0)
                    self.set_inventory(str(inventory_item_id), location_id, quantity)

            print(f"  [Shopify] {sku}: {action} successfully")

            # WHY SLEEP: Shopify rate limits API calls to 2/second.
            # Without this delay, rapid calls get throttled and fail.
            time.sleep(0.6)
            return action

        except requests.exceptions.HTTPError as e:
            print(f"  [Shopify] ERROR on {sku}: {e.response.status_code} — {e.response.text[:200]}")
            return "failed"
        except Exception as e:
            print(f"  [Shopify] ERROR on {sku}: {str(e)[:200]}")
            return "failed"


def run(
    selected_products: list[dict],
    listings: list[dict],
    prices: list[dict],
    stocks: list[dict]
) -> dict:
    """
    Main entry point — syncs all selected products to Shopify.

    Called by the manager after all agents have run.
    Uses the same data the agents already produced — no re-processing.

    Returns a summary dict for the daily report.
    """
    print("\n  [Shopify] Starting product sync...")

    try:
        client = ShopifySync()
        location_id = client.get_location_id()
    except Exception as e:
        print(f"  [Shopify] SETUP FAILED: {e}")
        print("  [Shopify] Skipping sync — check your .env credentials.")
        return {"created": 0, "updated": 0, "failed": 0, "skipped": True}

    # Build quick lookup maps so we can match data by SKU
    listing_map = {l["supplier_sku"]: l for l in listings}
    price_map   = {p["supplier_sku"]: p for p in prices}
    stock_map   = {s["supplier_sku"]: s for s in stocks}

    results = {"created": 0, "updated": 0, "failed": 0, "skipped": False}

    total = len(selected_products)
    for i, product in enumerate(selected_products, 1):
        sku = product["supplier_sku"]
        print(f"  [Shopify] Syncing {i}/{total}: {sku} — {product['name']}")

        listing   = listing_map.get(sku, {})
        price_data = price_map.get(sku, {})
        stock_data = stock_map.get(sku, {})

        if not listing or not price_data:
            print(f"  [Shopify] WARNING: Missing listing or price data for {sku} — skipping")
            results["failed"] += 1
            continue

        action = client.sync_product(listing, price_data, stock_data, product, location_id)
        results[action] = results.get(action, 0) + 1

    print(f"\n  [Shopify] Sync complete: {results['created']} created, "
          f"{results['updated']} updated, {results['failed']} failed.")
    return results