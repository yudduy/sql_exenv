#!/usr/bin/env python3
"""
Script to download BIRD Mini-Dev dataset from HuggingFace
and explore its structure for PostgreSQL integration.
"""

from datasets import load_dataset
import json
import os

def download_bird_dataset():
    """Download and explore BIRD Mini-Dev dataset from HuggingFace."""

    print("Downloading BIRD Mini-Dev dataset from HuggingFace...")
    print("This may take a few minutes...\n")

    try:
        # Load the dataset
        dataset = load_dataset("birdsql/bird_mini_dev")

        # Access the PostgreSQL version
        pg_data = dataset["mini_dev_pg"]

        print(f"✓ Successfully loaded dataset!")
        print(f"  Total PostgreSQL instances: {len(pg_data)}")
        print()

        # Display the first few examples
        print("=" * 80)
        print("FIRST 3 EXAMPLES FROM DATASET:")
        print("=" * 80)

        for i, example in enumerate(pg_data[:3]):
            print(f"\n--- Example {i+1} ---")
            print(f"Database: {example.get('db_id', 'N/A')}")
            print(f"Question: {example.get('question', 'N/A')}")
            print(f"SQL: {example.get('SQL', 'N/A')[:100]}...")
            print(f"Difficulty: {example.get('difficulty', 'N/A')}")

        print("\n" + "=" * 80)
        print("DATASET SCHEMA:")
        print("=" * 80)
        print(f"Keys in each example: {list(pg_data[0].keys())}")
        print()

        # Save all data to a local JSON file for easy access
        output_file = "bird_mini_dev_postgresql.json"
        print(f"Saving dataset to {output_file}...")

        # Convert to list of dicts
        data_list = [dict(example) for example in pg_data]

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=2, ensure_ascii=False)

        print(f"✓ Saved {len(data_list)} examples to {output_file}")

        # Get unique databases
        unique_dbs = set(example['db_id'] for example in data_list)
        print(f"\nUnique databases ({len(unique_dbs)}):")
        for db in sorted(unique_dbs):
            count = sum(1 for ex in data_list if ex['db_id'] == db)
            print(f"  - {db}: {count} queries")

        return data_list

    except Exception as e:
        print(f"✗ Error downloading dataset: {e}")
        print("\nTrying alternative approach...")

        # Alternative: Try to load from cache or download URL
        print("Please ensure you have 'datasets' library installed:")
        print("  pip install datasets")
        return None

if __name__ == "__main__":
    download_bird_dataset()
