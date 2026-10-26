#!/usr/bin/env python3
"""export-chat.py - keep this project's Claude Code chats and memory with it.

    python3 tools/export-chat.py

Copies everything Claude Code stores for this folder into local/claude/:

- chat/<session>.jsonl        the raw transcripts, exactly as Claude Code wrote them
- chat/<session>/subagents/   transcripts of helper agents started in a session
- memory/                     Claude's saved memory for this project
- history.jsonl               the prompt history lines that belong to this folder
- TRANSCRIPT-<session>.md     a readable version: your messages, Claude's replies,
                              and one line per tool call (tool output is left out)

local/ is not in git: transcripts carry personal details and full tool output.
tools/backup.sh copies it to the backup stick alongside the git bundle.
Run it again at any time; it overwrites the previous export.
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE = os.path.expanduser("~/.claude")
# Claude Code keys a project by its path with "/" replaced by "-".
SOURCE = os.path.join(CLAUDE, "projects", HERE.replace("/", "-"))
DEST = os.path.join(HERE, "local", "claude")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or []
                     if isinstance(b, dict) and b.get("type") == "text")


def _tool_line(block: dict) -> str:
    args = block.get("input") or {}
    what = (args.get("description") or args.get("file_path") or args.get("url")
            or args.get("query") or args.get("prompt", "")[:80] or "")
    return f"> *{block.get('name')}* - {str(what).strip()}"


def render(jsonl_path: str) -> str:
    out = []
    for line in open(jsonl_path, encoding="utf-8"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        kind, message = entry.get("type"), entry.get("message") or {}
        stamp = (entry.get("timestamp") or "")[:19].replace("T", " ")
        content = message.get("content")
        if kind == "user" and isinstance(content, str):
            text = content.strip()
            # Skip injected notices; keep what the person typed.
            if text and not text.startswith("<"):
                out.append(f"\n---\n\n### You - {stamp}\n\n{text}\n")
        elif kind == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and block.get("text", "").strip():
                    out.append(f"\n**Claude:** {block['text'].strip()}\n")
                elif block.get("type") == "tool_use":
                    out.append(_tool_line(block))
    return "# Claude Code chat\n" + "\n".join(out) + "\n"


def main() -> int:
    if not os.path.isdir(SOURCE):
        print(f"no Claude Code data for this folder at {SOURCE}")
        return 1
    os.makedirs(os.path.join(DEST, "chat"), exist_ok=True)
    sessions = 0
    for name in sorted(os.listdir(SOURCE)):
        path = os.path.join(SOURCE, name)
        if name.endswith(".jsonl"):
            shutil.copy2(path, os.path.join(DEST, "chat", name))
            session = name[:-len(".jsonl")]
            with open(os.path.join(DEST, f"TRANSCRIPT-{session}.md"), "w",
                      encoding="utf-8") as handle:
                handle.write(render(path))
            sessions += 1
        elif os.path.isdir(path) and name != "memory":
            shutil.copytree(path, os.path.join(DEST, "chat", name), dirs_exist_ok=True)
    memory = os.path.join(SOURCE, "memory")
    if os.path.isdir(memory):
        shutil.copytree(memory, os.path.join(DEST, "memory"), dirs_exist_ok=True)
    history = os.path.join(CLAUDE, "history.jsonl")
    if os.path.exists(history):
        with open(history, encoding="utf-8") as src, \
                open(os.path.join(DEST, "history.jsonl"), "w", encoding="utf-8") as dst:
            for line in src:
                if f'"{HERE}"' in line:
                    dst.write(line)
    print(f"exported {sessions} session(s) and memory to {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
