# Shopify Dropshipping Ops Agent

A multi-agent hierarchical system that automates Shopify dropshipping
operations end-to-end. Built for the Coderra AI Engineering assignment.

## What it does

Runs a 7-step autonomous pipeline:
1. Selects the 10 best products from a 30-SKU supplier catalog
2. Generates AI-powered Shopify listings (titles, bullets, descriptions, SEO)
3. Calculates sell prices guaranteed at ≥25% margin after all fees
4. Routes incoming orders (fulfil / backorder / substitute)
5. QA-reviews listings for false claims using a second LLM
6. Syncs everything live to a Shopify store via REST API
7. Produces a daily_report.md summarising all operations

## Architecture

See [architecture.md](architecture.md) for the full agent hierarchy and data flow.

## Multi-LLM Design

| Agent | Model | Why |
|-------|-------|-----|
| Listing Agent | llama3 via Ollama | Creative writing task |
| QA Agent | mistral via Ollama | Critical analysis task |

Both models run locally — completely free, no API key required.

## $0 Setup

### Prerequisites
- Python 3.9+
- Git
- [Ollama](https://ollama.com) installed

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/shopify-ops-agent.git
cd shopify-ops-agent
```

### 2. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Pull the LLM models (free, runs locally)
```bash
ollama pull llama3
ollama pull mistral
```

### 5. Configure environment (optional — for live Shopify sync)
Create a `.env` file:

SHOPIFY_SHOP_URL=yourstore.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxx

Without these, the pipeline runs in simulation mode and still produces
all 7 output files. Shopify sync is simply skipped.

### 6. Run the pipeline
```bash
python -m app run --catalog data/supplier_catalog.csv --orders data/orders.csv --out out/
```

## Output Files

| File | Description |
|------|-------------|
| `out/selection.json` | 10 selected SKUs with composite scores |
| `out/listings.json` | LLM-generated Shopify product content |
| `out/price_update.csv` | Calculated sell prices, AU and world |
| `out/stock_update.csv` | Inventory levels and reorder alerts |
| `out/order_actions.json` | Routing decisions and customer emails |
| `out/listing_redlines.json` | QA findings — over-claims flagged |
| `out/daily_report.md` | Complete human-readable summary |

## Pricing Formula