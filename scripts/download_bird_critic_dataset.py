#!/usr/bin/env python3
"""
Download BIRD-CRITIC flash-exp-200 dataset from HuggingFace.

This script downloads the official BIRD-CRITIC evaluation dataset (200 tasks)
from HuggingFace Hub and saves it to the expected location for evaluation.
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List

try:
    from datasets import load_dataset
except ImportError:
    print("ERROR: datasets library not installed. Run: pip install datasets")
    sys.exit(1)


def download_flash_exp_dataset(output_path: Path) -> List[Dict[str, Any]]:
    """
    Download BIRD-CRITIC flash-exp dataset from HuggingFace.

    Args:
        output_path: Path where to save the dataset

    Returns:
        List of task dictionaries
    """
    print("Downloading BIRD-CRITIC flash-exp dataset from HuggingFace...")
    print("Dataset: birdsql/bird-critic-1.0-flash-exp")
    print()

    try:
        # Load dataset from HuggingFace Hub
        dataset = load_dataset("birdsql/bird-critic-1.0-flash-exp", split="flash")

        print(f"✓ Dataset loaded successfully")
        print(f"  Total records: {len(dataset)}")
        print()

        # Convert to list of dictionaries
        tasks = []
        for item in dataset:
            tasks.append(dict(item))

        return tasks

    except Exception as e:
        print(f"✗ Error downloading dataset: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Check internet connection")
        print("  2. Verify dataset name: birdsql/bird-critic-1.0-flash-exp")
        print("  3. Try: huggingface-cli login (if authentication required)")
        raise


def validate_dataset_structure(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate that the dataset has the expected structure.

    Args:
        tasks: List of task dictionaries

    Returns:
        Validation statistics
    """
    print("Validating dataset structure...")

    required_fields = [
        "instance_id",
        "db_id",
        "query",
        "issue_sql",
        "preprocess_sql",
        "clean_up_sql",
        "efficiency",
        "category"
    ]

    stats = {
        "total_tasks": len(tasks),
        "missing_fields": {},
        "unique_db_ids": set(),
        "unique_instance_ids": set(),
        "categories": {},
        "efficiency_count": 0,
    }

    for i, task in enumerate(tasks):
        # Check required fields
        for field in required_fields:
            if field not in task:
                if field not in stats["missing_fields"]:
                    stats["missing_fields"][field] = []
                stats["missing_fields"][field].append(i)

        # Collect statistics
        if "db_id" in task:
            stats["unique_db_ids"].add(task["db_id"])

        if "instance_id" in task:
            stats["unique_instance_ids"].add(task["instance_id"])

        if "category" in task:
            category = task["category"]
            stats["categories"][category] = stats["categories"].get(category, 0) + 1

        if task.get("efficiency", False):
            stats["efficiency_count"] += 1

    # Convert sets to counts
    stats["unique_db_count"] = len(stats["unique_db_ids"])
    stats["unique_instance_count"] = len(stats["unique_instance_ids"])
    stats["unique_db_ids"] = sorted(list(stats["unique_db_ids"]))
    stats["unique_instance_ids"] = sorted(list(stats["unique_instance_ids"]))

    return stats


def print_validation_report(stats: Dict[str, Any]):
    """Print human-readable validation report."""
    print()
    print("=" * 70)
    print("DATASET VALIDATION REPORT")
    print("=" * 70)
    print(f"Total Tasks:           {stats['total_tasks']}")
    print(f"Unique Instance IDs:   {stats['unique_instance_count']}")
    print(f"Unique Databases:      {stats['unique_db_count']}")
    print(f"Efficiency Tasks:      {stats['efficiency_count']}")
    print()

    print("Categories:")
    for category, count in sorted(stats["categories"].items()):
        pct = (count / stats["total_tasks"]) * 100
        print(f"  {category:20s}: {count:3d} ({pct:5.1f}%)")
    print()

    print("Databases:")
    for db_id in stats["unique_db_ids"][:15]:  # Show first 15
        print(f"  - {db_id}")
    if len(stats["unique_db_ids"]) > 15:
        print(f"  ... and {len(stats['unique_db_ids']) - 15} more")
    print()

    if stats["missing_fields"]:
        print("⚠ WARNING: Missing fields detected:")
        for field, indices in stats["missing_fields"].items():
            print(f"  {field}: missing in {len(indices)} tasks")
        print()
    else:
        print("✓ All required fields present in all tasks")
        print()

    # Validate instance_id range
    expected_ids = set(range(200))
    actual_ids = set(stats["unique_instance_ids"])
    if actual_ids == expected_ids:
        print("✓ All instance_ids 0-199 present")
    else:
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        if missing:
            print(f"⚠ Missing instance_ids: {sorted(list(missing))[:10]}...")
        if extra:
            print(f"⚠ Extra instance_ids: {sorted(list(extra))[:10]}...")

    print("=" * 70)


def save_dataset(tasks: List[Dict[str, Any]], output_path: Path):
    """Save dataset to JSONL format."""
    print()
    print(f"Saving dataset to: {output_path}")

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save as JSONL (one JSON object per line)
    with open(output_path, "w") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    print(f"✓ Dataset saved successfully")
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    """Main entry point."""
    # Define output path
    project_root = Path(__file__).parent.parent
    output_path = project_root / "BIRD-CRITIC-1" / "baseline" / "data" / "flash_exp_200.jsonl"

    print("=" * 70)
    print("BIRD-CRITIC Dataset Download")
    print("=" * 70)
    print()

    # Download dataset
    try:
        tasks = download_flash_exp_dataset(output_path)
    except Exception as e:
        print(f"\n✗ Failed to download dataset: {e}")
        return 1

    # Validate structure
    stats = validate_dataset_structure(tasks)
    print_validation_report(stats)

    # Save to file
    save_dataset(tasks, output_path)

    print()
    print("✓ Dataset download complete!")
    print()
    print("Next steps:")
    print("  1. Review validation report above")
    print("  2. Check dataset file: " + str(output_path))
    print("  3. Run test case framework verification")

    return 0


if __name__ == "__main__":
    sys.exit(main())
