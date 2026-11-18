"""Preview docs at the same project-path prefix used by GitHub Pages."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DOCS = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8833)
    parser.add_argument("--base-path", default="/taskiller-backend")
    args = parser.parse_args()
    prefix = "/" + args.base_path.strip("/") if args.base_path.strip("/") else ""

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            clean = urlsplit(path).path
            if prefix and clean.startswith(prefix + "/"):
                path = path[len(prefix) :]
            return super().translate_path(path)

        def do_GET(self):
            path = urlsplit(self.path).path
            if prefix and path in {"/", prefix}:
                self.send_response(302)
                self.send_header("Location", prefix + "/")
                self.end_headers()
            elif prefix and not path.startswith(prefix + "/"):
                self.send_error(404)
            else:
                super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(DOCS)))
    print(f"Field guide: http://127.0.0.1:{args.port}{prefix}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
