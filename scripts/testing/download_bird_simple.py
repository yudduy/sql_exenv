#!/usr/bin/env python3
"""
Simple script to download BIRD Mini-Dev dataset using HTTP requests (no heavy dependencies).
"""

import json
import urllib.request
import os

def download_from_huggingface():
    """Download BIRD dataset directly from HuggingFace using HTTP."""

    print("Attempting to download BIRD Mini-Dev dataset from HuggingFace...")

    # HuggingFace dataset URL (parquet format)
    base_url = "https://huggingface.co/datasets/birdsql/bird_mini_dev"

    print(f"\nDataset repository: {base_url}")
    print("\nNote: The dataset is available in parquet format on HuggingFace.")
    print("For this MVP, we'll use the mini_dev repository's JSON files")
    print("which contain example queries from various models.\n")

    # Check if we can find JSON files in the mini_dev repository
    json_files = []
    for root, dirs, files in os.walk("mini_dev"):
        for file in files:
            if file.endswith(".json") and "postgresql" in file.lower():
                json_files.append(os.path.join(root, file))

    if json_files:
        print(f"Found {len(json_files)} PostgreSQL JSON files in mini_dev repository:")
        for f in json_files[:5]:
            print(f"  - {f}")
        return json_files
    else:
        print("No PostgreSQL JSON files found in mini_dev repository.")
        print("\nAlternative approaches:")
        print("1. Install datasets library in a virtualenv")
        print("2. Download manually from Google Drive:")
        print("   https://drive.google.com/file/d/13VLWIwpw5E3d5DUkMvzw7hvHE67a4XkG/view?usp=sharing")
        print("3. Use the bird-bench.github.io website")
        return None

if __name__ == "__main__":
    files = download_from_huggingface()

    if files:
        print("\n" + "=" * 80)
        print("NEXT STEPS:")
        print("=" * 80)
        print("1. These JSON files contain predicted SQL from various models")
        print("2. We need the actual ground truth data with database schemas")
        print("3. Recommended: Download the complete package from Google Drive")
        print("4. Or: Use the datasets library with proper venv setup")
