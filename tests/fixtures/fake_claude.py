"""A fake `claude` for tests. Reads FAKE_CLAUDE_MODE and emits a canned
--output-format json envelope on stdout. Never calls the network."""
import os
import sys
import time


def main() -> int:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "success")
    # drain stdin (the runner pipes the prompt in); we ignore it
    try:
        sys.stdin.read()
    except Exception:
        pass
    if mode == "hang":
        time.sleep(30)
        return 0
    if mode == "error":
        print('{"type":"result","is_error":true,"total_cost_usd":0.0,"result":"failed"}')
        return 1
    # success
    print('{"type":"result","subtype":"success","is_error":false,'
          '"total_cost_usd":0.01,"result":"done","session_id":"s1"}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
