"""
Quick test — verifies Shopify credentials work before running full pipeline.
Run this first: python test_shopify.py
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

shop_url = os.getenv("SHOPIFY_SHOP_URL")
token = os.getenv("SHOPIFY_ACCESS_TOKEN")

if not shop_url or not token:
    print("ERROR: Missing credentials in .env file")
    exit(1)

url = f"https://{shop_url}/admin/api/2024-01/shop.json"
headers = {"X-Shopify-Access-Token": token}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    shop = response.json()["shop"]
    print(f"SUCCESS — Connected to: {shop['name']}")
    print(f"Store URL: {shop['domain']}")
    print(f"Plan: {shop['plan_name']}")
else:
    print(f"FAILED — Status {response.status_code}: {response.text}")