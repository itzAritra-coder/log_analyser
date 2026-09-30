# Log Analyzer

A small client/server tool that analyzes application log files. The client streams a log file to an HTTP server, the server analyzes it, and the client prints a readable summary of errors per service.

Pure Python standard library.** Nothing to install; requires Python 3.8+.
Streaming design.** Logs of any size use the same small, constant amount of memory.
Tested.** 13 unit and integration tests, run automatically on every push with GitHub Actions.

Example

python client.py sample.log

Lines processed: 25
Unparseable lines: 4

Service Name          Error count
payment-service                 4
billing-service                 2
inventory-service               1
auth-service                    0
notification-service            0

Top offender: payment-service


Log format

Each line must look like this:

2026-09-18 10:23:45 ERROR payment-service Connection timeout after 30s


`date time LEVEL service message`

- Levels: `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` (uppercase only).
- The date and time must be real values (for example `2026-13-45` is rejected).
- The service name is a single word with no spaces, followed by a non-empty message.
- Any line that does not match counts as **unparseable**.

Quick start

Open two terminals in the project folder. On macOS/Linux use `python3` in place of `python`.

Terminal 1: start the server
python server.py

It prints `Listening on http://127.0.0.1:8080` and keeps running. Stop it with `Ctrl+C`.

Terminal 2: analyze a log
python client.py sample.log


## How it scales

- The client streams the file from disk and the server reads it in 64 KB chunks, analyzing lines as they arrive. No full file is ever held in memory.
- Time: O(n) for n lines. Memory: O(s) for s distinct services, plus a small fixed buffer.

Limitations

- Uploads need a `Content-Length` header; chunked transfer encoding is not supported.
- The server is a simple single-process Python server. For heavy production traffic, put it behind a production WSGI/ASGI server.
- Memory grows with the number of *distinct service names*, which is small in real logs.