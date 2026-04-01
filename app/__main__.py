"""
CLI Entry Point
---------------
This file is what makes `python -m app run ...` work.

WHY -m app (module mode):
  Running `python -m app` tells Python to look for app/__main__.py
  and run it. This is the standard way to make a Python package
  executable from the command line — cleaner than `python app/main.py`.
"""

import argparse
import sys
from app.agents.manager import run

def main():
    parser = argparse.ArgumentParser(
        description="Shopify Dropshipping Ops Agent — Multi-agent pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m app run --catalog data/supplier_catalog.csv --orders data/orders.csv --out out/
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the full agent pipeline")
    run_parser.add_argument("--catalog", required=True, help="Path to supplier_catalog.csv")
    run_parser.add_argument("--orders", required=True, help="Path to orders.csv")
    run_parser.add_argument("--out", default="out/", help="Output directory (default: out/)")

    args = parser.parse_args()

    if args.command == "run":
        run(
            catalog_path=args.catalog,
            orders_path=args.orders,
            out_dir=args.out
        )

if __name__ == "__main__":
    main()