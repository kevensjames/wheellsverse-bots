"""Fake `gh` for tests. `gh pr create ...` prints a canned PR url; if the first
non-flag arg is 'fail', exit non-zero to simulate a gh failure. 'exists' mode
simulates an already-open PR: `pr create` fails with 'already exists' and
`pr view` recovers the url. No network."""
import sys


def main() -> int:
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "fail":
        sys.stderr.write("gh: simulated failure\n")
        return 1
    if mode == "exists":
        # args after 'exists' are the gh subcommand
        sub = args[1:]
        if sub[:2] == ["pr", "create"]:
            sys.stderr.write("a pull request for branch ... already exists\n")
            return 1
        if sub[:2] == ["pr", "view"]:
            print("https://example.invalid/acme/pull/7")
            return 0
        return 1
    # args looks like: ["pr", "create", "--head", "...", ...]
    print("https://example.invalid/acme/pull/1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
