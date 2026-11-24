"""Real loopback HTTP fixture; production transport/parser/persistence stay intact."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class OllamaServer:
    def __init__(self, callback, *, loaded=False, context=32768, split=7):
        self.callback, self.context, self.split = callback, context, split
        self.active = context if loaded else None
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == "/api/ps":
                    self.reply({"models": [{"name": "fixture", "context_length": fixture.active}]
                                if fixture.active else []})
                else:
                    self.reply({"version": "0.33.3"})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, payload))
                if self.path == "/api/show":
                    self.reply({"model_info": {"gemma.context_length": 262144}})
                elif self.path == "/api/generate":
                    fixture.active = payload.get("options", {}).get("num_ctx", fixture.context)
                    self.reply({"done": True, "done_reason": "load"})
                else:
                    content, reason = fixture.callback(payload)
                    self.chat(payload, content, reason)

            def reply(self, payload):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def chat(self, payload, content, reason):
                event = {"message": {"role": "assistant", "content": content}, "done": reason is not None,
                         "done_reason": reason, "prompt_eval_count": 300, "eval_count": 100}
                if not payload.get("stream"):
                    self.reply(event)
                    return
                # Multiple NDJSON events and split UTF-8/TCP writes exercise both boundaries.
                events = [{"message": {"content": content[index:index + 11]}, "done": False}
                          for index in range(0, len(content), 11)]
                if reason is not None:
                    events.append({**event, "message": {"content": ""}})
                data = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    for index in range(0, len(data), fixture.split):
                        self.wfile.write(data[index:index + fixture.split])
                    self.wfile.flush()
                except (ConnectionError, OSError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def outline(beats=3, *, ending=None):
    records = [{"kind": "title", "text": "配信"},
               {"kind": "chapter", "index": 1, "title": "配信", "objective": "開始から締めまで",
                "scenes": [{"purpose": f"話題{i}", "start": f"前{i}", "end": f"後{i}"} for i in range(beats)]}]
    if ending:
        records.append({"kind": "ending", "text": ending})
    return json.dumps({"records": records}, ensure_ascii=False)


def dialogue(payload, *, tag="", complete=True):
    user = json.loads(payload["messages"][1]["content"])
    targets = next(section["accepted_dialogue_and_current_request"]["source_target_characters"]
                   for section in user["sections"] if "accepted_dialogue_and_current_request" in section)
    response = {}
    for source, count in targets.items():
        offset = sum((index + 1) * ord(char) for index, char in enumerate(source + tag)) * 301
        text = "配信の話を進めます。" + "".join(chr(0x4E00 + (offset + index) % 20000)
                                              for index in range(max(0, count - 10)))
        response[source] = {"lines": [{"speaker": "A", "text": text, "rate": "1.0", "gap": "0.7",
                                       "direction": "穏やかに"}], "complete": complete}
    return json.dumps(response, ensure_ascii=False)
