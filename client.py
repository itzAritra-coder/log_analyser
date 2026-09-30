"""CLI client: streams a log file to the server and prints a readable summary."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description="Analyze a log file via the server.")
    p.add_argument("logfile")
    p.add_argument("--url", default="http://127.0.0.1:8080", help="server base URL")
    p.add_argument("--timeout", type=float, default=600, help="seconds (default 600)")
    a = p.parse_args()

    try:
        size = os.path.getsize(a.logfile)
        f = open(a.logfile, "rb")
    except OSError as e:
        sys.exit(f"Cannot read {a.logfile}: {e}")

    with f:  # file object is streamed from disk, never fully loaded
        req = urllib.request.Request(
            a.url.rstrip("/") + "/analyses", data=f, method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8",
                     "Content-Length": str(size)},
        )
        try:
            with urllib.request.urlopen(req, timeout=a.timeout) as resp:
                result = json.load(resp)
        except urllib.error.HTTPError as e:
            sys.exit(f"Server returned {e.code}: {e.read().decode(errors='replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"Cannot reach server at {a.url}: {e.reason}")
        except OSError as e:
            sys.exit(f"Connection problem: {e}")

    print(f"Lines processed: {result['lines_processed']:,}")
    print(f"Unparseable lines: {result['unparseable_lines']:,}\n")
    rows = result["errors_by_service"]
    name_w = max([len("Service Name")] + [len(s) for s in rows]) + 4
    num_w = max([len("Error count")] + [len(f"{n:,}") for n in rows.values()])
    print(f"{'Service Name':<{name_w}}{'Error count':>{num_w}}")
    for svc, n in rows.items():
        print(f"{svc:<{name_w}}{n:>{num_w},}")
    print(f"\nTop offender: {result['top_offender'] or 'none'}")


if __name__ == "__main__":
    main()