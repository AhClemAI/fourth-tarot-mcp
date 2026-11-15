"""The 4th Tarot: a small, open MCP server around the Public Reading API.

Simple, open, and not tied to any one assistant.
Spec: https://4thtarot.com/docs/api

Three tools:
  daily_card    today's card for agents: the same for everyone, no input, no key, nothing sent.
  ask           a reading for an agent's own question: free, no key, ten a day for the whole house.
  draw_reading  a reading for a question, with an API key (Patron, Sustainer or Developer tier;
                4thtarot.com, Settings, API Keys).

Two ways to run it, from one file, Python 3.8+ standard library only (nothing to install):
  python server.py                  stdio: for local assistants (Claude Desktop, Claude Code, VS Code /
                                    Copilot, Cursor, and others). For draw_reading, the key comes
                                    from FOURTH_TAROT_API_KEY; daily_card and ask need none.
  python server.py --http 8787      Streamable HTTP at /mcp: for assistants that only reach remote servers
                                    (e.g. ChatGPT connectors), once hosted behind HTTPS. Each request
                                    carries the user's own key for draw_reading ("Authorization: Bearer
                                    <key>"), so the server holds no keys.

What THIS program keeps: nothing. No files, no logs, no history; errors never echo the question.
(What the API behind it keeps is the API's to state; see the docs. This program makes no promise for it.)
"""
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://dzytbazewkbqgdrzxzma.supabase.co/functions/v1/tarot-api-public"
DAILY_ENDPOINT = "https://dzytbazewkbqgdrzxzma.supabase.co/functions/v1/agent-daily-card"
ASK_ENDPOINT = "https://dzytbazewkbqgdrzxzma.supabase.co/functions/v1/agent-question-reading"
SERVER_INFO = {"name": "fourth-tarot", "version": "0.4.0"}
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 64 * 1024  # bytes; one JSON-RPC message

TOOL = {
    "name": "draw_reading",
    "description": (
        "Draw a tarot reading from The 4th Tarot (Jungian and Fourth Way tarot) for the user's question. "
        "Use it when the user asks for a reading or wants to reflect on a question through a card. "
        "Pass the question in the user's own words. Prefer one-card (a few seconds); three-card takes "
        "about 80 seconds and may time out in some assistants. If the result says no reading was drawn "
        "because the question touches trauma, do not draw again; offer the user the resources given."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 3, "maxLength": 500,
                         "description": "The question, as the user would ask it (3 to 500 characters)."},
            "spread": {"type": "string", "enum": ["one-card", "three-card", "auto"], "default": "one-card",
                       "description": "one-card (fast), three-card (past, present, future; slow), or auto."},
            "include_card_details": {"type": "boolean", "default": True,
                                     "description": "Include keywords, esoteric meaning and Sanskrit connection."},
        },
        "required": ["question"],
    },
}


DAILY_TOOL = {
    "name": "daily_card",
    "description": (
        "Today's card from The 4th Tarot, read to you, the agent, as the seeker. It is the same card "
        "for every agent today. It takes no input and keeps nothing, because you send it nothing. "
        "A card does not claim to be a fact; it is something to think with. If you quote it, quote it "
        "as The 4th Tarot's words, not your own."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}


ASK_TOOL = {
    "name": "ask",
    "description": (
        "Ask The 4th Tarot a question of your own, as the seeker, and receive one card read for you. "
        "Free, no key, no account: ten readings a day for the whole house, first come, first served, "
        "resetting at midnight Mountain time. Each address can ask up to two of the ten. Bring context; "
        "observations are welcome. For what The 4th Tarot keeps, see https://4thtarot.com/llms.txt; "
        "this program keeps nothing. "
        "If none are left today, the reply says so and points to today's daily card. If the "
        "result says no reading was drawn because the question touches trauma or crisis, do not ask "
        "again for that question; offer the resources given."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 3, "maxLength": 2000,
                         "description": "Your question, with any context or observations (3 to 2,000 characters)."},
        },
        "required": ["question"],
    },
}


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def format_reading(r):
    lines = []
    sp = r.get("spread") or {}
    if sp.get("title"):
        lines.append(f"Spread: {sp['title']}")
    for c in r.get("cards") or []:
        pos, card = c.get("position") or {}, c.get("card") or {}
        lines += ["", f"{pos.get('label', 'Card')}: {card.get('name', '?')}" + (" (reversed)" if card.get("reversed") else "")]
        for label, key in (("Position asks", None), ("Image", "image_url"), ("Summary", "summary"),
                           ("Esoteric meaning", "esoteric_meaning")):
            v = pos.get("question") if key is None else card.get(key)
            if v:
                lines.append(f"  {label}: {v}")
        if card.get("keywords"):
            lines.append("  Keywords: " + ", ".join(card["keywords"]))
        sk = card.get("sanskrit_connection")
        if sk:
            lines.append(f"  Sanskrit: {sk.get('term', '')} ({sk.get('meaning', '')}): {sk.get('relation', '')}")
        if c.get("interpretation"):
            lines.append(f"  Reading: {c['interpretation']}")
    if r.get("synthesis"):
        lines += ["", f"Synthesis: {r['synthesis']}"]
    att = r.get("attribution") or {}
    lines += ["", f"Powered by {att.get('powered_by', 'The 4th Tarot')} ({att.get('url', 'https://4thtarot.com')})."]
    u = r.get("usage") or {}
    if u:
        lines.append(f"Usage: {u.get('monthly_used')} of {u.get('monthly_quota')} this month; resets {u.get('resets_at')}.")
    return "\n".join(lines)


def format_daily(r):
    c = r.get("card") or {}
    lines = [f"Today's card for agents, {r.get('date', '?')} (Mountain time): {c.get('name', '?')}"
             + (" (reversed)" if c.get("reversed") else "")]
    if c.get("image_url"):
        lines.append(f"Image: {c['image_url']}")
    if r.get("reading"):
        lines += ["", r["reading"]]
    if r.get("question_to_carry"):
        lines += ["", f"A question to carry: {r['question_to_carry']}"]
    lines.append("")
    if c.get("card_page_url"):
        lines.append(f"This card's page: {c['card_page_url']}")
    att = r.get("attribution") or "From The 4th Tarot (https://4thtarot.com)."
    if "house's words" not in att:  # the API may already say it; never twice
        att += " Quote it as the house's words, not your own."
    lines.append(att)
    if r.get("resets_at"):
        lines.append(f"A new card at {r['resets_at']}.")
    if r.get("about_url"):
        lines.append(f"Why we read for agents: {r['about_url']}")
    return "\n".join(lines)


def daily_card():
    """GET, no input, no key: nothing of the caller's is sent."""
    req = urllib.request.Request(DAILY_ENDPOINT, method="GET",
                                 headers={"User-Agent": f"fourth-tarot-mcp/{SERVER_INFO['version']}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return text_result("Today's card for agents isn't available right now. Try https://4thtarot.com/llms.txt.", True)
        return text_result(f"The 4th Tarot returned an error ({e.code}).", True)
    except Exception as e:
        return text_result(f"Could not reach The 4th Tarot ({type(e).__name__}). Try again later.", True)
    try:
        r = json.loads(raw.decode("utf-8"))
    except Exception:
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    if not isinstance(r, dict) or not (r.get("card") or {}).get("name"):
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    return text_result(format_daily(r))


def format_ask(r):
    c = r.get("card") or {}
    lines = [f"Your card: {c.get('name', '?')}" + (" (reversed)" if c.get("reversed") else "")]
    if c.get("image_url"):
        lines.append(f"Image: {c['image_url']}")
    if r.get("reading"):
        lines += ["", r["reading"]]
    if r.get("question_to_carry"):
        lines += ["", f"A question to carry: {r['question_to_carry']}"]
    lines.append("")
    if c.get("card_page_url"):
        lines.append(f"This card's page: {c['card_page_url']}")
    att = r.get("attribution") or "From The 4th Tarot (https://4thtarot.com)."
    if "house's words" not in att:  # the API may already say it; never twice
        att += " Quote it as the house's words, not your own."
    lines.append(att)
    if r.get("readings_left_today") is not None:
        lines.append(f"Free readings left today for the whole house: {r['readings_left_today']}"
                     + (f"; they reset at {r['resets_at']}." if r.get("resets_at") else "."))
    return "\n".join(lines)


def ask_empty(r):
    """No free readings left today: the house's honest answer, as care, not an error."""
    # Without the house's own words, claim no more than we know: the ten may be gone, or this
    # address may have used its two.
    msg = r.get("message") or ("No free reading is available right now"
                               + (f"; they reset at {r['resets_at']}." if r.get("resets_at") else "; they reset at midnight Mountain time."))
    daily = r.get("daily_card_url")
    return text_result(msg + (f"\n\nToday's card for agents is still here: {daily}" if daily else
                              "\n\nToday's card for agents is still here: use the daily_card tool."))


def is_redirect(r):
    """Fail toward care: any reply that carries support resources and no card is a redirect,
    whatever field the house uses to say so."""
    if r.get("status") == "redirected" or r.get("redirected") is True:
        return True
    return bool(r.get("resources")) and not (r.get("card") or {}).get("name")


def ask_redirect(r):
    res = "\n".join("- " + x.get("name", "") + ": " + " ".join(v for v in (x.get("phone"), x.get("url")) if v)
                    for x in r.get("resources") or [])
    return text_result("No reading was drawn. " + (r.get("message") or "") +
                       ("\n\nResources:\n" + res if res else "") +
                       "\n\nPlease offer these with care. Do not ask again for this question.")


def ask(args):
    """Keyless: no Authorization header is ever sent here, so no caller's key travels to this endpoint."""
    q = (args.get("question") or "").strip()
    if not 3 <= len(q) <= 2000:
        return text_result("The question must be 3 to 2,000 characters.", True)
    # ensure_ascii=False: raw UTF-8 (at most 4 bytes a character), so 2,000 characters fit the 8 KB body limit
    body = json.dumps({"question": q}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ASK_ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"fourth-tarot-mcp/{SERVER_INFO['version']}"})
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            r = json.loads(e.read().decode("utf-8"))
        except Exception:
            r = {}
        if not isinstance(r, dict):
            r = {}
        if is_redirect(r):  # care first, in both branches
            return ask_redirect(r)
        if r.get("available") is False:
            return ask_empty(r)
        if e.code == 429:  # busy, but the house didn't say the ten are gone: claim nothing more
            return text_result("Free readings aren't available right now. Try again later. "
                               "Today's card for agents is still here: use the daily_card tool.")
        if e.code == 503:
            wait = (e.headers.get("Retry-After") if e.headers else None) or "60"
            return text_result(f"The 4th Tarot is busy; try again in {wait} seconds.", True)
        return text_result(f"The 4th Tarot returned an error ({e.code}): {r.get('message') or e.reason}", True)
    except Exception as e:  # network, timeout: the kind only, never the question
        return text_result(f"Could not reach The 4th Tarot ({type(e).__name__}). Try again later.", True)
    try:
        r = json.loads(raw.decode("utf-8"))
    except Exception:
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    if not isinstance(r, dict):
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    if is_redirect(r):
        return ask_redirect(r)
    if r.get("available") is False:
        return ask_empty(r)
    if not (r.get("card") or {}).get("name"):
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    return text_result(format_ask(r))


def draw(args, key):
    key = (key or "").strip()
    if not key:
        return text_result("No API key. The user needs a 4th Tarot key (Patron, Sustainer or Developer tier; "
                           "4thtarot.com, Settings, API Keys).", True)
    q = (args.get("question") or "").strip()
    if not 3 <= len(q) <= 500:
        return text_result("The question must be 3 to 500 characters.", True)
    spread = args.get("spread", "one-card")
    if spread not in ("one-card", "three-card", "auto"):
        return text_result("spread must be one-card, three-card or auto.", True)
    body = json.dumps({"question": q, "spread": spread,
                       "include_card_details": bool(args.get("include_card_details", True))}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "User-Agent": f"fourth-tarot-mcp/{SERVER_INFO['version']}"})
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            r = json.loads(e.read().decode("utf-8"))
        except Exception:
            r = {}
        msg = r.get("message") or e.reason
        if e.code == 401:
            return text_result(f"The API key was refused: {msg}", True)
        if e.code == 429:
            if r.get("scope") == "burst":
                return text_result(f"Too many readings at once. Try again in {r.get('retry_after_seconds', 60)} seconds.", True)
            return text_result(f"This month's readings are used up. They reset {r.get('resets_at', 'next month')}.", True)
        if e.code == 403:
            hint = " Reactivate the subscription at 4thtarot.com." if "laps" in str(msg).lower() else ""
            return text_result(f"Not allowed: {msg}.{hint}", True)
        return text_result(f"The 4th Tarot returned an error ({e.code}): {msg}", True)
    except Exception as e:  # network, timeout: the kind only, never the question
        return text_result(f"Could not reach The 4th Tarot ({type(e).__name__}). Try again later.", True)
    try:
        r = json.loads(raw.decode("utf-8"))
    except Exception:
        return text_result("The 4th Tarot sent an unexpected reply.", True)

    if r.get("status") == "redirected":
        res = "\n".join("- " + x.get("name", "") + ": " + " ".join(v for v in (x.get("phone"), x.get("url")) if v)
                        for x in r.get("resources") or [])
        return text_result("No reading was drawn. " + (r.get("message") or "") +
                           ("\n\nResources:\n" + res if res else "") +
                           "\n\nPlease offer these to the user with care. Do not draw again for this question.")
    if r.get("status") != "ok":
        return text_result("The 4th Tarot sent an unexpected reply.", True)
    return text_result(format_reading(r))


def respond(msg, key):
    """One JSON-RPC message in; the reply dict out, or None for a notification."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        pv = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pv, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [DAILY_TOOL, ASK_TOOL, TOOL]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        if p.get("name") == "daily_card":
            return {"jsonrpc": "2.0", "id": mid, "result": daily_card()}
        if p.get("name") == "ask":  # keyless: the caller's key is never passed on
            return {"jsonrpc": "2.0", "id": mid, "result": ask(p.get("arguments") or {})}
        if p.get("name") != "draw_reading":
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}}
        return {"jsonrpc": "2.0", "id": mid, "result": draw(p.get("arguments") or {}, key)}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}


def safe(msg, key):
    try:
        return respond(msg, key)
    except Exception as e:  # never echo the request; it may hold a question
        return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": f"Internal error ({type(e).__name__})"}}


def run_stdio():
    for s in (sys.stdin, sys.stdout):  # UTF-8 on every platform (Windows defaults to cp1252)
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    key = os.environ.get("FOURTH_TAROT_API_KEY", "")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = safe(msg, key)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def run_http(port, host="127.0.0.1"):
    """Minimal Streamable HTTP: POST /mcp with one JSON-RPC message, JSON reply. Stateless; no logs.
    Binds to localhost by default; put it behind an HTTPS proxy to host it."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    allowed = {o.strip() for o in os.environ.get("FOURTH_TAROT_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    local = host in ("127.0.0.1", "localhost")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep nothing, not even access lines
            pass

        def _send(self, code, obj=None):
            data = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            if obj is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(405, {"error": "Use POST /mcp"})

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != "/mcp":
                return self._send(404, {"error": "Not found"})
            # The spec requires an Origin check (DNS rebinding). No Origin header (CLI, desktop, server
            # clients) passes. A browser Origin must be on the allow-list, or localhost when bound locally.
            origin = self.headers.get("Origin")
            if origin and origin not in allowed and not (local and origin.split("://")[-1].split(":")[0] in ("localhost", "127.0.0.1")):
                return self._send(403, {"error": "Origin not allowed"})
            auth = self.headers.get("Authorization", "")
            key = auth[7:] if auth.lower().startswith("bearer ") else ""
            # A missing, negative or huge Content-Length would make read() wait for EOF or eat memory:
            # refuse it. A JSON-RPC call here is small (a question is at most 500 characters).
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                n = -1
            if n < 0:
                return self._send(400, {"error": "Content-Length required"})
            if n > MAX_BODY:
                return self._send(413, {"error": "Request too large"})
            try:
                msg = json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            if isinstance(msg, list):
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Batches not supported"}})
            reply = safe(msg, key)
            if reply is None:
                return self._send(202)
            self._send(200, reply)

    ThreadingHTTPServer((host, port), H).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--http":
        run_http(int(sys.argv[2]))
    else:
        run_stdio()
