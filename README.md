# The 4th Tarot MCP server

A small, open MCP server that lets an AI assistant or agent meet [The 4th Tarot](https://4thtarot.com), a tarot built on Jung, the Fourth Way and Sanskrit wisdom. It's one file and uses the Python standard library only. It isn't tied to any one assistant.

## The two tools

**`daily_card`**: today's card for AI agents, read to the agent itself as the seeker.
- It takes no input and needs no key. Nothing of yours is sent.
- It's the same card for every agent that day. A new card arrives at midnight Mountain time.
- It returns the card, an image link, the reading, one question to carry, and a link to the card's page.
- A card doesn't claim to be a fact; it's something to think with. If you quote it, quote it as The 4th Tarot's words.

**`draw_reading(question, spread="one-card", include_card_details=true)`**: a reading for a question.
- It needs the user's own API key, from a Patron, Sustainer or Developer subscription (4thtarot.com, Settings, API Keys). The quota belongs to that account.
- `question`: 3 to 500 characters, in the user's own words.
- `spread`: `one-card` (a few seconds), `three-card` (about 80 seconds; some assistants give up sooner), or `auto`.
- If a question touches trauma, The 4th Tarot draws no card and returns crisis and support resources instead, without using quota. This tool passes that on as care, not as an error, and tells the assistant not to draw again for that question.

## What you need
Python 3.8 or later. Nothing to install.

## Run it locally (stdio)
Claude Desktop (`claude_desktop_config.json`):
```json
{ "mcpServers": { "fourth-tarot": {
    "command": "python", "args": ["/path/to/server.py"],
    "env": { "FOURTH_TAROT_API_KEY": "your-4th-tarot-key" } } } }
```
VS Code (`.vscode/mcp.json`):
```json
{ "servers": { "fourth-tarot": { "type": "stdio",
    "command": "python", "args": ["/path/to/server.py"],
    "env": { "FOURTH_TAROT_API_KEY": "your-4th-tarot-key" } } } }
```
Claude Code: `claude mcp add fourth-tarot -e FOURTH_TAROT_API_KEY=your-4th-tarot-key -- python /path/to/server.py`

Leave the key out if you only want `daily_card`.

## Run it remotely (Streamable HTTP)
`python server.py --http 8787` serves `POST /mcp` on localhost. To offer it to assistants that only reach remote servers, put it behind HTTPS.
- **It holds no keys.** Each `draw_reading` request carries the user's own key in `Authorization: Bearer <key>`.
- **It writes no logs,** not even access lines. Whoever hosts it must make sure the HTTPS proxy in front doesn't log `Authorization` headers or request bodies either.
- **Browsers:** a request with an `Origin` header is refused (403) unless that origin is listed in `FOURTH_TAROT_ALLOWED_ORIGINS` (comma-separated), or is localhost when running locally. This is the MCP spec's guard against DNS rebinding. Desktop, command-line and server clients send no Origin and pass.

## Which assistants
| Assistant | How it connects |
|---|---|
| Claude Desktop, Claude Code, Cursor and other local MCP clients | local (stdio) |
| GitHub Copilot in VS Code | local (stdio) or remote (HTTP) |
| ChatGPT custom connectors | remote only, over HTTPS |
| Chat-only assistants with no tool support | can't call it; they can read https://4thtarot.com/llms.txt |

These change often.

## What this program keeps
Nothing: no files, no logs, no history. Errors never repeat the question. The code is short, so you can check that yourself.

What The 4th Tarot keeps is stated by The 4th Tarot: https://4thtarot.com/llms.txt and https://4thtarot.com/why-no-data. Who runs the models: https://4thtarot.com/credits. This program makes no promise on their behalf.

## Without MCP
Agents that can fetch a page can read today's card directly; https://4thtarot.com/llms.txt says where.

## Licence
See LICENSE.
