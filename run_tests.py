#!/usr/bin/env python3
"""
run_tests.py — WheellsVerse test runner (no pytest required).

Usage:
    python run_tests.py              # all tests
    python run_tests.py --fast       # skip API endpoint tests (no server)
    python run_tests.py --module literary_qc
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Module import checks ──────────────────────────────────────────────────────

IMPORT_CHECKS = [
    ("core.literary_qc", "LiteraryQCAgent"),
    ("core.continuity_engine", "ContinuityEngine"),
    ("bots.books.volume_completion_bot", "VolumeCompletionBot"),
    ("bots.books.publisher_engine.pipeline", "PublisherEnginePipeline"),
    ("bots.books.publisher_engine.story_agent", "run"),
    ("bots.books.publisher_engine.editing_agent", "run"),
    ("bots.books.publisher_engine.style_agent", "run"),
    ("bots.books.publisher_engine.market_agent", "run"),
    ("bots.books.publisher_engine.design_agent", "run"),
    ("bots.books.publisher_engine.marketing_agent", "run"),
    ("bots.books.publisher_engine.distribution_agent", "run"),
]


def run_import_checks():
    passed = 0
    failed = 0
    print("\n── Import Checks ───────────────────────────────────────────────")
    for module, attr in IMPORT_CHECKS:
        try:
            mod = __import__(module, fromlist=[attr])
            assert hasattr(mod, attr), f"{module} missing '{attr}'"
            print(f"  ✅  {module}.{attr}")
            passed += 1
        except Exception as e:
            print(f"  ❌  {module}.{attr}  →  {e}")
            failed += 1
    return passed, failed


# ── Test suite ────────────────────────────────────────────────────────────────

TEST_MODULES = {
    "continuity_engine": "tests.test_continuity_engine",
    "literary_qc": "tests.test_literary_qc",
    "publisher_pipeline": "tests.test_publisher_pipeline",
    "api_endpoints": "tests.test_api_endpoints",
    "volume_completion": "tests.test_volume_completion",
}


def run_test_module(name: str, dotted: str) -> unittest.TestResult:
    print(f"\n── {name} ───────────────────────────────────────────────")
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(dotted)
    except Exception as e:
        print(f"  ❌  Could not load {dotted}: {e}")
        result = unittest.TestResult()
        result.errors.append((None, str(e)))
        return result

    runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout)
    result = runner.run(suite)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="WheellsVerse test runner")
    parser.add_argument("--fast", action="store_true",
                        help="Skip API endpoint tests (requires running server)")
    parser.add_argument("--module", metavar="NAME",
                        help="Run only this module (e.g. literary_qc)")
    args = parser.parse_args()

    start = time.time()
    print("=" * 60)
    print("  WheellsVerse Test Suite")
    print("=" * 60)

    # Import checks first
    imp_pass, imp_fail = run_import_checks()

    # Determine which test modules to run
    to_run = {}
    if args.module:
        if args.module in TEST_MODULES:
            to_run = {args.module: TEST_MODULES[args.module]}
        else:
            print(f"Unknown module: {args.module}. Choose from: {list(TEST_MODULES)}")
            sys.exit(1)
    else:
        to_run = dict(TEST_MODULES)
        if args.fast:
            to_run.pop("api_endpoints", None)
            print("\n  [--fast] Skipping api_endpoints tests")

    # Run each module
    total_tests = 0
    total_failures = 0
    total_errors = 0
    module_results = {}

    for name, dotted in to_run.items():
        result = run_test_module(name, dotted)
        module_results[name] = result
        total_tests += result.testsRun
        total_failures += len(result.failures)
        total_errors += len(result.errors)

    # Summary
    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Import checks:  {imp_pass} passed, {imp_fail} failed")
    print(f"  Unit tests:     {total_tests} run, {total_failures} failures, {total_errors} errors")
    print(f"  Elapsed:        {elapsed:.1f}s")
    print()

    for name, result in module_results.items():
        ok = len(result.failures) == 0 and len(result.errors) == 0
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {name:<28}  {result.testsRun} tests")

    total_problems = imp_fail + total_failures + total_errors
    if total_problems == 0:
        print("\n  All checks passed. 🎉")
    else:
        print(f"\n  {total_problems} problem(s) found.")

    pass_rate = (total_tests - total_failures - total_errors) / max(total_tests, 1) * 100
    print(f"  Pass rate: {pass_rate:.0f}%")
    print()

    sys.exit(0 if total_problems == 0 else 1)


if __name__ == "__main__":
    main()
