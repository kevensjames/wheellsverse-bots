"""Fake `gh` for tests. `gh pr create ...` prints a canned PR url; if the first
non-flag arg is 'fail', exit non-zero to simulate a gh failure. No network."""
import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "fail":
        sys.stderr.write("gh: simulated failure\n")
        return 1
    # args looks like: ["pr", "create", "--head", "...", ...]
    print("https://example.invalid/acme/pull/1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
