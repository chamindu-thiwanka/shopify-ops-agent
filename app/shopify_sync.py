# # """
# # Shopify Sync Module
# # -------------------
# # PURPOSE:
# #   This module is the bridge between your pipeline's output data and
# #   your real Shopify store. It takes the listings, prices, and stock
# #   levels that your agents already produced and pushes them live.

# # WHY A SEPARATE FILE (not added to existing agents):
# #   The existing agents are pure business logic — they work with or
# #   without Shopify. Keeping Shopify as a separate module means:
# #     1. You can run the pipeline locally without any Shopify credentials
# #     2. If Shopify's API changes, you only update this one file
# #     3. The simulation still works perfectly if Shopify is down
# #     4. It's easy to swap Shopify for another platform later

# # HOW IT WORKS:
# #   1. Authenticate with your store using the access token from .env
# #   2. For each listing: check if the product already exists (by SKU)
# #      - If it does: UPDATE it (price, stock, description)
# #      - If it doesn't: CREATE it (full product with all details)
# #   3. After creating/updating: set the inventory level
# #   4. Log every action so you can see exactly what happened

# # SHOPIFY API BASICS:
# #   Shopify's REST Admin API works like this:
# #   - Products:  POST /admin/api/2024-01/products.json      (create)
# #                PUT  /admin/api/2024-01/products/{id}.json (update)
# #   - Inventory: POST /admin/api/2024-01/inventory_levels/set.json (set stock)
  
# #   Every request needs the X-Shopify-Access-Token header.
# #   Rate limit: 2 requests/second on development stores (we add delays).
# # """

# # import os
# # import time
# # import requests
# # from dotenv import load_dotenv

# # load_dotenv()


# # class ShopifySync:
# #     """
# #     Handles all communication with the Shopify Admin REST API.
    
# #     WHY A CLASS:
# #       We need to store the shop URL and token once, then reuse them
# #       across many API calls. A class is cleaner than passing credentials
# #       to every function individually.
# #     """

# #     def __init__(self):
# #         self.shop_url = os.getenv("SHOPIFY_SHOP_URL", "").rstrip("/")
# #         self.token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
# #         self.api_version = "2024-01"

# #         if not self.shop_url or not self.token:
# #             raise ValueError(
# #                 "SHOPIFY_SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set in your .env file.\n"
# #                 "See README for setup instructions."
# #             )

# #         self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"
# #         self.headers = {
# #             "X-Shopify-Access-Token": self.token,
# #             "Content-Type": "application/json"
# #         }
# #         print(f"  [Shopify] Connected to: {self.shop_url}")

# #     def _get(self, endpoint: str) -> dict:
# #         """
# #         Make a GET request to the Shopify API.
# #         Used for reading existing products and inventory locations.
# #         """
# #         url = f"{self.base_url}{endpoint}"
# #         response = requests.get(url, headers=self.headers, timeout=30)
# #         response.raise_for_status()
# #         return response.json()

# #     def _post(self, endpoint: str, data: dict) -> dict:
# #         """
# #         Make a POST request — used for creating products and setting inventory.
# #         """
# #         url = f"{self.base_url}{endpoint}"
# #         response = requests.post(url, headers=self.headers, json=data, timeout=30)
# #         response.raise_for_status()
# #         return response.json()

# #     def _put(self, endpoint: str, data: dict) -> dict:
# #         """
# #         Make a PUT request — used for updating existing products.
# #         """
# #         url = f"{self.base_url}{endpoint}"
# #         response = requests.put(url, headers=self.headers, json=data, timeout=30)
# #         response.raise_for_status()
# #         return response.json()

# #     def get_location_id(self) -> str:
# #         """
# #         Get the inventory location ID for your store.

# #         WHY WE NEED THIS:
# #           Shopify tracks inventory per physical location (warehouse, store, etc).
# #           Development stores have one default location. We need its ID to tell
# #           Shopify which location's inventory to update when we set stock levels.
# #           Without this, the inventory update call fails.
# #         """
# #         data = self._get("/locations.json")
# #         locations = data.get("locations", [])
# #         if not locations:
# #             raise ValueError("No locations found in your Shopify store.")
# #         location_id = str(locations[0]["id"])
# #         print(f"  [Shopify] Using location ID: {location_id}")
# #         return location_id

# #     def find_existing_product(self, sku: str) -> dict | None:
# #         """
# #         Search for an existing product by SKU in your Shopify store.

# #         WHY WE CHECK FIRST:
# #           If you run the pipeline twice, you don't want 20 duplicate products
# #           in your store. By searching for the SKU first, we can UPDATE an
# #           existing product instead of creating a second copy.

# #           Shopify stores SKUs on product variants. We search all products
# #           and check each variant's SKU field.
# #         """
# #         data = self._get(f"/products.json?limit=250")
# #         products = data.get("products", [])

# #         for product in products:
# #             for variant in product.get("variants", []):
# #                 if variant.get("sku") == sku:
# #                     return product

# #         return None  # Not found — will create new

# #     def build_product_payload(
# #         self,
# #         listing: dict,
# #         price_data: dict,
# #         stock_data: dict,
# #         product: dict
# #     ) -> dict:
# #         """
# #         Build the JSON payload that Shopify's API expects for a product.

# #         WHY THIS STRUCTURE:
# #           Shopify has a specific shape for product data. Understanding it:
# #           - body_html: the description (Shopify renders HTML, so we use <p> tags)
# #           - variants: a product can have multiple variants (sizes, colours).
# #             We have one variant per product — we set price and SKU here.
# #           - images: Shopify downloads the image from the URL you provide.
# #           - tags: comma-separated string (not a list)
# #         """
# #         # Convert bullet points to HTML list for Shopify's description field
# #         bullets_html = "<ul>" + "".join(
# #             f"<li>{b}</li>" for b in listing.get("bullets", [])
# #         ) + "</ul>"

# #         # Full description: bullets + paragraph text
# #         full_description = (
# #             bullets_html +
# #             f"<p>{listing.get('description', '')}</p>"
# #         )

# #         payload = {
# #             "product": {
# #                 "title": listing.get("title", product["name"]),
# #                 "body_html": full_description,
# #                 "vendor": product.get("brand", ""),
# #                 "product_type": product.get("category", ""),
# #                 "tags": ", ".join(listing.get("tags", [])),
# #                 "status": "draft",   # draft = not visible to customers yet
# #                                      # Change to "active" to make it live
# #                 "variants": [
# #                     {
# #                         "sku": product["supplier_sku"],
# #                         "price": str(price_data["sell_price_au"]),
# #                         "inventory_management": "shopify",
# #                         # inventory_management = "shopify" tells Shopify to
# #                         # track this product's stock automatically
# #                         "inventory_policy": "deny",
# #                         # "deny" = don't allow purchase when out of stock
# #                         # (alternative: "continue" = allow backorders)
# #                         "weight": product.get("weight_kg", 0),
# #                         "weight_unit": "kg",
# #                         "fulfillment_service": "manual"
# #                     }
# #                 ],
# #                 "images": [
# #                     {"src": product.get("image_url", "")}
# #                 ] if product.get("image_url") else [],
# #                 "metafields": [
# #                     {
# #                         "namespace": "ops_agent",
# #                         "key": "seo_title",
# #                         "value": listing.get("seo_title", ""),
# #                         "type": "single_line_text_field"
# #                     },
# #                     {
# #                         "namespace": "ops_agent",
# #                         "key": "seo_description",
# #                         "value": listing.get("seo_description", ""),
# #                         "type": "single_line_text_field"
# #                     }
# #                 ]
# #             }
# #         }
# #         return payload

# #     def set_inventory(self, inventory_item_id: str, location_id: str, quantity: int):
# #         """
# #         Set the stock level for a product variant at your store location.

# #         WHY A SEPARATE CALL:
# #           In Shopify, inventory is set separately from product creation.
# #           First you create the product (which creates an inventory_item_id),
# #           then you call this endpoint to set how many units are available.
# #           This mirrors how real warehouses work — the product exists
# #           independently of how many you have in stock.
# #         """
# #         payload = {
# #             "location_id": int(location_id),
# #             "inventory_item_id": int(inventory_item_id),
# #             "available": quantity
# #         }
# #         self._post("/inventory_levels/set.json", payload)

# #     def sync_product(
# #         self,
# #         listing: dict,
# #         price_data: dict,
# #         stock_data: dict,
# #         product: dict,
# #         location_id: str
# #     ) -> str:
# #         """
# #         Create or update a single product in Shopify.

# #         Returns:
# #           "created" — new product was added to your store
# #           "updated" — existing product was updated
# #           "failed"  — something went wrong (logged, pipeline continues)

# #         WHY CREATE-OR-UPDATE PATTERN:
# #           Running the pipeline multiple times should be safe.
# #           First run: creates 10 products.
# #           Second run: updates the same 10 products (price changes, new listings).
# #           Without this pattern, you'd get 10 new duplicate products every run.
# #         """
# #         sku = product["supplier_sku"]

# #         try:
# #             # Check if product already exists
# #             existing = self.find_existing_product(sku)
# #             payload = self.build_product_payload(listing, price_data, stock_data, product)

# #             if existing:
# #                 # UPDATE existing product
# #                 product_id = existing["id"]
# #                 result = self._put(f"/products/{product_id}.json", payload)
# #                 action = "updated"
# #             else:
# #                 # CREATE new product
# #                 result = self._post("/products.json", payload)
# #                 action = "created"

# #             # Get the inventory item ID from the first variant
# #             shopify_product = result.get("product", {})
# #             variants = shopify_product.get("variants", [])

# #             if variants:
# #                 inventory_item_id = variants[0].get("inventory_item_id")
# #                 if inventory_item_id:
# #                     quantity = stock_data.get("available_stock", 0)
# #                     self.set_inventory(str(inventory_item_id), location_id, quantity)

# #             print(f"  [Shopify] {sku}: {action} successfully")

# #             # WHY SLEEP: Shopify rate limits API calls to 2/second.
# #             # Without this delay, rapid calls get throttled and fail.
# #             time.sleep(0.6)
# #             return action

# #         except requests.exceptions.HTTPError as e:
# #             print(f"  [Shopify] ERROR on {sku}: {e.response.status_code} — {e.response.text[:200]}")
# #             return "failed"
# #         except Exception as e:
# #             print(f"  [Shopify] ERROR on {sku}: {str(e)[:200]}")
# #             return "failed"


# # def run(
# #     selected_products: list[dict],
# #     listings: list[dict],
# #     prices: list[dict],
# #     stocks: list[dict]
# # ) -> dict:
# #     """
# #     Main entry point — syncs all selected products to Shopify.

# #     Called by the manager after all agents have run.
# #     Uses the same data the agents already produced — no re-processing.

# #     Returns a summary dict for the daily report.
# #     """
# #     print("\n  [Shopify] Starting product sync...")

# #     try:
# #         client = ShopifySync()
# #         location_id = client.get_location_id()
# #     except Exception as e:
# #         print(f"  [Shopify] SETUP FAILED: {e}")
# #         print("  [Shopify] Skipping sync — check your .env credentials.")
# #         return {"created": 0, "updated": 0, "failed": 0, "skipped": True}

# #     # Build quick lookup maps so we can match data by SKU
# #     listing_map = {l["supplier_sku"]: l for l in listings}
# #     price_map   = {p["supplier_sku"]: p for p in prices}
# #     stock_map   = {s["supplier_sku"]: s for s in stocks}

# #     results = {"created": 0, "updated": 0, "failed": 0, "skipped": False}

# #     total = len(selected_products)
# #     for i, product in enumerate(selected_products, 1):
# #         sku = product["supplier_sku"]
# #         print(f"  [Shopify] Syncing {i}/{total}: {sku} — {product['name']}")

# #         listing   = listing_map.get(sku, {})
# #         price_data = price_map.get(sku, {})
# #         stock_data = stock_map.get(sku, {})

# #         if not listing or not price_data:
# #             print(f"  [Shopify] WARNING: Missing listing or price data for {sku} — skipping")
# #             results["failed"] += 1
# #             continue

# #         action = client.sync_product(listing, price_data, stock_data, product, location_id)
# #         results[action] = results.get(action, 0) + 1

# #     print(f"\n  [Shopify] Sync complete: {results['created']} created, "
# #           f"{results['updated']} updated, {results['failed']} failed.")
# #     return results

# """
# Shopify Sync Module
# -------------------
# PURPOSE:
#   Bridge between pipeline output data and the live Shopify store.
#   Takes listings, prices, and stock levels from the agents and pushes
#   them to Shopify via the Admin REST API.

# WHY A SEPARATE FILE:
#   The existing agents are pure business logic — they work with or without
#   Shopify. Keeping sync isolated means:
#     1. Pipeline runs fine without Shopify credentials (simulation mode)
#     2. If Shopify's API changes, only this file needs updating
#     3. Easy to swap Shopify for another platform in future

# HOW IT WORKS:
#   1. Authenticate using the access token from .env
#   2. For each product: check if it already exists by SKU
#        - Exists → UPDATE (price, description, stock)
#        - New    → CREATE (full product with all details)
#   3. Set inventory quantity using a two-step process:
#        a. connect_inventory_to_location() — register item at location
#        b. set_inventory()                — write the actual quantity
#   4. Log every action

# SHOPIFY REST API:
#   Products:  POST /products.json        (create)
#              PUT  /products/{id}.json   (update)
#   Inventory: POST /inventory_levels/connect.json  (step 1)
#              POST /inventory_levels/set.json       (step 2)

#   Rate limit: 2 requests/second on development stores.
#   We sleep 0.6s between products to stay safely under the limit.

# INVENTORY FIX NOTES:
#   CREATE flow: inventory_item_id comes from the POST response variant.
#                connect then set works correctly.
#   UPDATE flow: inventory_item_id must be fetched from the EXISTING
#                product's variant before the PUT call, because Shopify
#                may not return inventory_item_id reliably in PUT responses.
#                This is why inventory showed 0 after updates — we were
#                trying to read inventory_item_id from the PUT response
#                which was unreliable.
# """

# import os
# import time
# import requests
# from dotenv import load_dotenv

# load_dotenv()


# class ShopifySync:
#     """
#     Handles all communication with the Shopify Admin REST API.

#     WHY A CLASS:
#       Stores the shop URL and token once, reuses them across all API
#       calls. Much cleaner than passing credentials to every function.
#     """

#     def __init__(self):
#         self.shop_url = os.getenv("SHOPIFY_SHOP_URL", "").rstrip("/")
#         self.token    = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
#         self.api_version = "2024-01"

#         if not self.shop_url or not self.token:
#             raise ValueError(
#                 "SHOPIFY_SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set "
#                 "in your .env file. See README for setup instructions."
#             )

#         self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"
#         self.headers  = {
#             "X-Shopify-Access-Token": self.token,
#             "Content-Type": "application/json"
#         }
#         print(f"  [Shopify] Connected to: {self.shop_url}")

#     # ── HTTP helpers ─────────────────────────────────────────────

#     def _get(self, endpoint: str) -> dict:
#         url = f"{self.base_url}{endpoint}"
#         r = requests.get(url, headers=self.headers, timeout=30)
#         r.raise_for_status()
#         return r.json()

#     def _post(self, endpoint: str, data: dict) -> dict:
#         url = f"{self.base_url}{endpoint}"
#         r = requests.post(url, headers=self.headers, json=data, timeout=30)
#         r.raise_for_status()
#         return r.json()

#     def _put(self, endpoint: str, data: dict) -> dict:
#         url = f"{self.base_url}{endpoint}"
#         r = requests.put(url, headers=self.headers, json=data, timeout=30)
#         r.raise_for_status()
#         return r.json()

#     # ── Store helpers ─────────────────────────────────────────────

#     def get_location_id(self) -> str:
#         """
#         Get the inventory location ID for your store.

#         WHY NEEDED:
#           Shopify tracks inventory per physical location. Development
#           stores have one default location. We need its ID to tell
#           Shopify where to set stock levels.
#         """
#         data = self._get("/locations.json")
#         locations = data.get("locations", [])
#         if not locations:
#             raise ValueError("No locations found in your Shopify store.")
#         location_id = str(locations[0]["id"])
#         print(f"  [Shopify] Using location ID: {location_id}")
#         return location_id

#     def find_existing_product(self, sku: str) -> dict | None:
#         """
#         Search for an existing product by SKU.

#         WHY CHECK FIRST:
#           Running the pipeline twice would create duplicates without this
#           check. By finding existing products by SKU, we UPDATE instead
#           of creating a second copy.

#           Shopify stores SKUs on variants. We scan all products and check
#           each variant's sku field.
#         """
#         data = self._get("/products.json?limit=250")
#         for product in data.get("products", []):
#             for variant in product.get("variants", []):
#                 if variant.get("sku") == sku:
#                     return product
#         return None

#     def get_inventory_item_id(self, product: dict) -> str | None:
#         """
#         Extract the inventory_item_id from a product's first variant.

#         WHY THIS EXISTS:
#           For UPDATE flows, we need the inventory_item_id from the
#           EXISTING product before calling the PUT endpoint.
#           Shopify's PUT response doesn't always include inventory_item_id
#           reliably, so we read it from the existing product object instead.
#           This is the fix for inventory showing 0 after update runs.
#         """
#         variants = product.get("variants", [])
#         if variants:
#             return str(variants[0].get("inventory_item_id", ""))
#         return None

#     # ── Product payload ───────────────────────────────────────────

#     def build_product_payload(
#         self,
#         listing: dict,
#         price_data: dict,
#         product: dict
#     ) -> dict:
#         """
#         Build the JSON payload Shopify's API expects for a product.

#         KEY FIELDS:
#           body_html        → description rendered as HTML in storefront
#           variants         → price and SKU live here (one variant per product)
#           images           → Shopify downloads from the URL you provide
#           tags             → comma-separated string, not a list
#           status: "draft"  → invisible to customers until manually activated
#         """
#         bullets_html = "<ul>" + "".join(
#             f"<li>{b}</li>" for b in listing.get("bullets", [])
#         ) + "</ul>"

#         full_description = bullets_html + f"<p>{listing.get('description', '')}</p>"

#         return {
#             "product": {
#                 "title":        listing.get("title", product["name"]),
#                 "body_html":    full_description,
#                 "vendor":       product.get("brand", ""),
#                 "product_type": product.get("category", ""),
#                 "tags":         ", ".join(listing.get("tags", [])),
#                 "status":       "draft",
#                 "variants": [{
#                     "sku":                  product["supplier_sku"],
#                     "price":                str(price_data["sell_price_au"]),
#                     "inventory_management": "shopify",
#                     "inventory_policy":     "deny",
#                     "weight":               product.get("weight_kg", 0),
#                     "weight_unit":          "kg",
#                     "fulfillment_service":  "manual"
#                 }],
#                 "images": [
#                     {"src": product.get("image_url", "")}
#                 ] if product.get("image_url") else [],
#                 "metafields": [
#                     {
#                         "namespace": "ops_agent",
#                         "key":       "seo_title",
#                         "value":     listing.get("seo_title", ""),
#                         "type":      "single_line_text_field"
#                     },
#                     {
#                         "namespace": "ops_agent",
#                         "key":       "seo_description",
#                         "value":     listing.get("seo_description", ""),
#                         "type":      "single_line_text_field"
#                     }
#                 ]
#             }
#         }

#     # ── Inventory helpers ─────────────────────────────────────────

#     def connect_inventory_to_location(
#         self, inventory_item_id: str, location_id: str
#     ):
#         """
#         Step 1 of 2: Register the inventory item at the store location.

#         WHY REQUIRED:
#           Shopify requires explicit "connection" before quantity can be set.
#           Without this, set.json returns 200 OK but writes nothing.
#           This is why Image 2 showed 0 even after creation.

#           Safe to call multiple times — Shopify ignores it if already
#           connected. We suppress errors here for exactly that reason.
#         """
#         try:
#             self._post("/inventory_levels/connect.json", {
#                 "location_id":           int(location_id),
#                 "inventory_item_id":     int(inventory_item_id),
#                 "relocate_if_necessary": False
#             })
#         except Exception:
#             pass  # Already connected — safe to continue to set

#     def set_inventory_quantity(
#         self, inventory_item_id: str, location_id: str, quantity: int
#     ):
#         """
#         Step 2 of 2: Write the actual stock quantity.

#         Always call connect_inventory_to_location() first.
#         """
#         self.connect_inventory_to_location(inventory_item_id, location_id)
#         self._post("/inventory_levels/set.json", {
#             "location_id":       int(location_id),
#             "inventory_item_id": int(inventory_item_id),
#             "available":         quantity
#         })

#     # ── Core sync ─────────────────────────────────────────────────

#     def sync_product(
#         self,
#         listing: dict,
#         price_data: dict,
#         stock_data: dict,
#         product: dict,
#         location_id: str
#     ) -> str:
#         """
#         Create or update a single product in Shopify, then set inventory.

#         Returns: "created" | "updated" | "failed"

#         WHY CREATE-OR-UPDATE:
#           First run  → creates 10 new products.
#           Second run → updates the same 10 (new listings, new prices).
#           Without this pattern, every run would add 10 duplicates.

#         INVENTORY LOGIC:
#           CREATE → inventory_item_id comes from POST response variant.
#           UPDATE → inventory_item_id comes from the EXISTING product
#                    variant (read BEFORE the PUT call). This is the key
#                    fix — PUT responses don't reliably include this field.
#         """
#         sku = product["supplier_sku"]

#         try:
#             existing = self.find_existing_product(sku)
#             payload  = self.build_product_payload(listing, price_data, product)

#             if existing:
#                 # ── UPDATE path ──────────────────────────────────
#                 # Read inventory_item_id from EXISTING product BEFORE PUT
#                 # This is the fix — don't rely on PUT response for this
#                 inventory_item_id = self.get_inventory_item_id(existing)

#                 self._put(f"/products/{existing['id']}.json", payload)
#                 action = "updated"

#             else:
#                 # ── CREATE path ──────────────────────────────────
#                 result = self._post("/products.json", payload)
#                 action = "created"

#                 # For creates, read inventory_item_id from POST response
#                 created_product   = result.get("product", {})
#                 inventory_item_id = self.get_inventory_item_id(created_product)

#             # Set inventory quantity using the two-step process
#             if inventory_item_id:
#                 quantity = stock_data.get("available_stock", 0)
#                 self.set_inventory_quantity(
#                     inventory_item_id, location_id, quantity
#                 )

#             print(f"  [Shopify] {sku}: {action} successfully")
#             time.sleep(0.6)  # Stay under the 2 requests/second rate limit
#             return action

#         except requests.exceptions.HTTPError as e:
#             print(
#                 f"  [Shopify] ERROR on {sku}: "
#                 f"{e.response.status_code} — {e.response.text[:200]}"
#             )
#             return "failed"
#         except Exception as e:
#             print(f"  [Shopify] ERROR on {sku}: {str(e)[:200]}")
#             return "failed"


# # ── Module entry point ────────────────────────────────────────────

# def run(
#     selected_products: list[dict],
#     listings: list[dict],
#     prices: list[dict],
#     stocks: list[dict]
# ) -> dict:
#     """
#     Sync all selected products to Shopify.

#     Called by the manager after all agents have run.
#     Uses data the agents already produced — no re-processing needed.
#     Returns a summary dict included in the daily report.
#     """
#     print("\n  [Shopify] Starting product sync...")

#     try:
#         client      = ShopifySync()
#         location_id = client.get_location_id()
#     except Exception as e:
#         print(f"  [Shopify] SETUP FAILED: {e}")
#         print("  [Shopify] Skipping sync — check your .env credentials.")
#         return {"created": 0, "updated": 0, "failed": 0, "skipped": True}

#     # Build fast lookup maps by SKU
#     listing_map = {l["supplier_sku"]: l for l in listings}
#     price_map   = {p["supplier_sku"]: p for p in prices}
#     stock_map   = {s["supplier_sku"]: s for s in stocks}

#     results = {"created": 0, "updated": 0, "failed": 0, "skipped": False}
#     total   = len(selected_products)

#     for i, product in enumerate(selected_products, 1):
#         sku = product["supplier_sku"]
#         print(f"  [Shopify] Syncing {i}/{total}: {sku} — {product['name']}")

#         listing    = listing_map.get(sku, {})
#         price_data = price_map.get(sku, {})
#         stock_data = stock_map.get(sku, {})

#         if not listing or not price_data:
#             print(f"  [Shopify] WARNING: Missing data for {sku} — skipping")
#             results["failed"] += 1
#             continue

#         action = client.sync_product(
#             listing, price_data, stock_data, product, location_id
#         )
#         results[action] = results.get(action, 0) + 1

#     print(
#         f"\n  [Shopify] Sync complete: {results['created']} created, "
#         f"{results['updated']} updated, {results['failed']} failed."
#     )
#     return results

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