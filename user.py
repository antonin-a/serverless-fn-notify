"""notify: one function, any notification destination (WhatsApp, Slack, email...).

A Python 3.12 function for the OVHcloud Serverless alpha. It is the shape of
the "notification template" the alpha needs while the platform has no Topics
(SNS-like) service yet: the handler formats a message, drops duplicates,
retries briefly, and hands the delivery to Apprise (https://github.com/caronc/apprise).

The destination is configuration, not code: the secret NOTIFY_URLS holds one
or more Apprise URLs. Change the URL, and the same deployed function talks to
WhatsApp, Slack, Teams, email, PagerDuty, a webhook... or several at once.

Runtime contract (starter function-python3.12-hello): the handler is `main`,
takes no argument, runs inside Flask (so `flask.request` is available) and
returns a JSON-serialisable value or a Flask Response.

  GET  /            the demo web page (a form that posts to this function)
  GET  /?format=json  status: destinations (secrets masked), counters
  POST /            send a notification. Body is JSON, either
                      {"title": "...", "body": "...", "id": "optional"}
                    or a CloudEvent (specversion, type, source, id, data):
                    what an Events Rule posts to a function.

Environment:
  NOTIFY_URLS        secret, comma-separated Apprise URLs (required to send)
                       whatsapp://TOKEN@PHONE_ID/33612345678      Meta Cloud API
                       twilio://SID:TOKEN@14155238886/w:33612345678  Twilio WhatsApp
                       json://localhost:9999/hook                 local receiver
  NOTIFY_TITLE       default title (default: "OVHcloud Serverless")
  NOTIFY_RETRIES     attempts per destination (default: 2)
  NOTIFY_CORS_ORIGIN Access-Control-Allow-Origin for cross-origin pages (default: *)
  NOTIFY_RELEASE     the release that deployed this revision (default: "dev")
"""

from __future__ import annotations

import collections
import json
import os
import socket
import time
from datetime import datetime, timezone

_IMPORT_STARTED = time.monotonic()
import apprise  # the only dependency, pinned in requirements.txt

APPRISE_IMPORT_MS = round((time.monotonic() - _IMPORT_STARTED) * 1000)

_STARTED_AT = time.monotonic()
_INSTANCE = socket.gethostname()
_CALLS = 0
_SENT = 0

# Duplicate protection on the message id (ce-id for a CloudEvent). It lives in
# the instance: a warm instance ignores a redelivery, a cold start forgets.
# Good enough for the alpha; a Topic will own delivery guarantees later.
_SEEN: collections.OrderedDict[str, float] = collections.OrderedDict()
_SEEN_MAX = 1000


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _destinations() -> apprise.Apprise:
    a = apprise.Apprise()
    for url in _env("NOTIFY_URLS", "").split(","):
        url = url.strip()
        if url and not a.add(url):
            # never echo the URL: it carries the token
            print(f"notify: ignored one NOTIFY_URLS entry (unrecognised scheme or malformed)")
    return a


def _safe_url(server) -> str:
    """Apprise masks the credentials of a URL, but not the custom headers
    (+Key=value) and pass-through parameters (-key=value) of the JSON, XML and
    Form plugins, where an API key usually travels: redact those too."""
    url = server.url(privacy=True)
    base, sep, query = url.partition("?")
    if not sep:
        return url
    parts = []
    for item in query.split("&"):
        key, eq, value = item.partition("=")
        if eq and key.startswith(("+", "-", "%2B", "%2D")):
            value = "***"
        parts.append(f"{key}{eq}{value}")
    return base + "?" + "&".join(parts)


def _masked(a: apprise.Apprise) -> list[dict]:
    return [{"service": s.service_name, "url": _safe_url(s)} for s in a]


def _normalise(payload: dict) -> tuple[str, str, str]:
    """Returns (id, title, body) from a plain message or a CloudEvent."""
    default_title = _env("NOTIFY_TITLE", "OVHcloud Serverless")
    if "specversion" in payload:  # CloudEvent, as posted by an Events Rule
        data = payload.get("data")
        if isinstance(data, dict):
            subject = data.get("name") or data.get("id") or payload.get("subject") or ""
            details = ", ".join(f"{k}: {v}" for k, v in data.items() if isinstance(v, (str, int, float)) and k not in ("name",))
        else:
            subject = payload.get("subject") or ""
            details = str(data) if data is not None else ""
        title = f"{default_title}: {payload.get('type', 'event')}"
        body = f"{subject}\nsource: {payload.get('source', '?')}\nat: {payload.get('time', '?')}\n{details}".strip()
        return str(payload.get("id", "")), title, body[:1000]
    return (
        str(payload.get("id", "")),
        str(payload.get("title") or default_title),
        str(payload.get("body") or payload.get("message") or "")[:1000],
    )


def _send(message_id: str, title: str, body: str) -> dict:
    global _SENT
    started = time.monotonic()
    if message_id:
        if message_id in _SEEN:
            return {"sent": False, "deduplicated": True, "id": message_id, "durationMs": 0}
        _SEEN[message_id] = time.monotonic()
        while len(_SEEN) > _SEEN_MAX:
            _SEEN.popitem(last=False)

    attempts = max(1, int(_env("NOTIFY_RETRIES", "2")))
    results = []
    for server in _destinations():
        ok = False
        tries = 0
        for tries in range(1, attempts + 1):
            ok = bool(server.notify(body=body, title=title))
            if ok:
                break
            time.sleep(0.5 * tries)
        results.append({"service": server.service_name, "url": _safe_url(server), "ok": ok, "attempts": tries})
    sent = bool(results) and all(r["ok"] for r in results)
    if sent:
        _SENT += 1
    return {
        "sent": sent,
        "deduplicated": False,
        "id": message_id or None,
        "title": title,
        "destinations": results,
        "durationMs": round((time.monotonic() - started) * 1000),
    }


def _status() -> dict:
    uptime = time.monotonic() - _STARTED_AT
    return {
        "destinations": _masked(_destinations()),
        "release": _env("NOTIFY_RELEASE", "dev"),
        "appriseVersion": apprise.__version__,
        "appriseImportMs": APPRISE_IMPORT_MS,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instance": {
            "hostname": _INSTANCE,
            "uptimeSeconds": round(uptime, 1),
            "coldStart": uptime < 5,
            "callsServed": _CALLS,
            "notificationsSent": _SENT,
            "seenIds": len(_SEEN),
        },
    }


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Serverless notify</title>
<style>
  :root { color-scheme: light dark; --accent: #0050d7; --muted: #6b7280; --bg: #f6f7fb; --card: #fff; --fg: #111; }
  @media (prefers-color-scheme: dark) { :root { --bg: #0f1115; --card: #1a1d24; --fg: #eee; --muted: #9aa0ab; } }
  body { margin: 0; font: 16px/1.5 -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--fg); }
  main { max-width: 640px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; } p.lead { color: var(--muted); margin: 0 0 20px; }
  .card { background: var(--card); border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  label { display: block; font-weight: 600; margin: 12px 0 4px; }
  input, textarea { width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #ccd; border-radius: 8px; font: inherit; background: transparent; color: inherit; }
  textarea { min-height: 90px; }
  button { margin-top: 14px; padding: 10px 18px; border: 0; border-radius: 8px; background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
  button.alt { background: transparent; color: var(--accent); border: 1px solid var(--accent); margin-left: 8px; }
  button:disabled { opacity: .5; }
  pre { background: rgba(127,127,127,.12); padding: 12px; border-radius: 8px; overflow: auto; font-size: 13px; }
  ul.dest { padding-left: 18px; margin: 6px 0; } code { font-size: 14px; }
  .ok { color: #15803d; font-weight: 600; } .ko { color: #b91c1c; font-weight: 600; }
  small { color: var(--muted); }
</style></head>
<body><main>
<h1>Send a notification</h1>
<p class="lead">This page is served by a Serverless function. The form posts to the same function, which delivers the message through Apprise to whatever <code>NOTIFY_URLS</code> says.</p>

<div class="card">
  <strong>Destinations</strong> <small>(secrets masked)</small>
  <ul class="dest" id="dest"><li><small>loading</small></li></ul>
  <small id="meta"></small>
</div>

<div class="card">
  <form id="f">
    <label for="title">Title</label>
    <input id="title" name="title" value="Hello from OVHcloud Serverless">
    <label for="body">Message</label>
    <textarea id="body" name="body">Deployment finished. The new revision is live.</textarea>
    <button type="submit" id="send">Send</button>
    <button type="button" class="alt" id="event">Send as a CloudEvent</button>
    <button type="button" class="alt" id="again">Send the same id again</button>
  </form>
  <p><small>"Send as a CloudEvent" posts what an Events Rule would post (an instance created event). "Send the same id again" shows the duplicate protection on the message id.</small></p>
</div>

<div class="card">
  <strong>Last answer</strong> <span id="verdict"></span>
  <pre id="out">nothing sent yet</pre>
</div>
</main>
<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let lastId = null;
  fetch("?format=json").then(r => r.json()).then(s => {
    $("dest").innerHTML = s.destinations.length
      ? s.destinations.map(d => `<li><b>${d.service}</b> <code>${d.url}</code></li>`).join("")
      : "<li class='ko'>no NOTIFY_URLS configured: nothing will be delivered</li>";
    $("meta").textContent = `apprise ${s.appriseVersion}, import ${s.appriseImportMs} ms, instance ${s.instance.hostname}, cold start ${s.instance.coldStart}, release ${s.release}`;
  });
  async function post(payload) {
    $("send").disabled = true; $("verdict").textContent = ""; $("out").textContent = "sending...";
    const t = performance.now();
    try {
      const r = await fetch(location.pathname, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const j = await r.json();
      j.roundTripMs = Math.round(performance.now() - t);
      $("out").textContent = JSON.stringify(j, null, 2);
      $("verdict").innerHTML = j.deduplicated ? "<span class='ko'>ignored: duplicate id</span>" : (j.sent ? "<span class='ok'>delivered</span>" : "<span class='ko'>not delivered</span>");
    } catch (e) { $("out").textContent = String(e); }
    $("send").disabled = false;
  }
  $("f").addEventListener("submit", (e) => { e.preventDefault(); lastId = "web-" + Date.now(); post({ id: lastId, title: $("title").value, body: $("body").value }); });
  $("event").addEventListener("click", () => {
    lastId = "evt-" + Date.now();
    post({ specversion: "1.0", id: lastId, type: "ovh.publiccloud.instance.created", source: "urn:v1:eu:resource:publicCloudProject:demo", time: new Date().toISOString(), subject: "instance", data: { name: "web-01", flavor: "b3-8", region: "GRA11", status: "ACTIVE" } });
  });
  $("again").addEventListener("click", () => { if (!lastId) { $("out").textContent = "send something first"; return; } post({ id: lastId, title: $("title").value, body: $("body").value }); });
})();
</script>
</body></html>
"""


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": _env("NOTIFY_CORS_ORIGIN", "*"),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def main():
    global _CALLS
    _CALLS += 1
    try:
        from flask import Response, request  # the platform's Python runtime runs handlers inside Flask
    except ImportError:
        return _status()
    try:
        method = request.method
    except RuntimeError:  # no request context
        return _status()

    if method == "OPTIONS":
        return Response("", status=204, headers=_cors_headers())
    if method == "POST":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return Response(json.dumps({"error": "expected a JSON object"}), status=400, mimetype="application/json", headers=_cors_headers())
        message_id, title, body = _normalise(payload)
        if not body:
            return Response(json.dumps({"error": "empty message"}), status=400, mimetype="application/json", headers=_cors_headers())
        result = _send(message_id, title, body)
        return Response(json.dumps(result, ensure_ascii=False), status=200 if result["sent"] or result["deduplicated"] else 502,
                        mimetype="application/json", headers=_cors_headers())
    if request.args.get("format") == "json":
        return _status()
    return Response(_PAGE, status=200, mimetype="text/html")


if __name__ == "__main__":
    # Local run: the same handler behind a local Flask server, like the platform does.
    from flask import Flask

    app = Flask(__name__)
    app.add_url_rule("/", "main", main, methods=["GET", "POST", "OPTIONS"])
    app.add_url_rule("/<path:_>", "main_any", lambda _: main(), methods=["GET", "POST", "OPTIONS"])
    port = int(_env("PORT", "8080"))
    print(f"notify: http://localhost:{port}/  destinations: {[d['url'] for d in _masked(_destinations())]}")
    app.run(host="127.0.0.1", port=port, debug=False)
