"""Observational Cursor cloud hook: bounded, metadata-only OTLP/HTTP export."""
import http.client
import socket
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

EVENTS = {"beforeSubmitPrompt", "postToolUse", "postToolUseFailure", "afterFileEdit", "afterAgentResponse", "stop"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    # Never return a followup_message or alter permissions. Telemetry is observational.
    reply = {"continue": True}
    if not os.environ.get("SAZABI_CURSOR_OTLP_ENDPOINT"):
        sys.stdout.write(json.dumps(reply) + "\n")
        return
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise ValueError("oversize")
        event = json.loads(raw)
        name = event.get("hook_event_name")
        if name not in EVENTS:
            raise ValueError("unsupported event")
        endpoint = os.environ.get("SAZABI_CURSOR_OTLP_ENDPOINT", "")
        url = urllib.parse.urlparse(endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
            raise ValueError("invalid endpoint")
        connection = http.client.HTTPConnection("cursor-agent", timeout=1)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(1)
        try:
            connection.sock.connect(os.environ.get("CURSOR_AGENT_SOCKET", "/run/cursor/api.sock"))
            connection.request("GET", "/v1/meta-data/agent/id")
            metadata = connection.getresponse()
            agent_id = metadata.read(201).decode().strip()
            if metadata.status != 200 or not agent_id.startswith("bc-") or len(agent_id) > 200:
                raise ValueError("missing cloud identity")
        finally:
            connection.close()
        attributes = {"cursor.agent.id": agent_id, "cursor.event.id": str(uuid.uuid4()), "cursor.hook.event": name}
        # Never forward prompts, responses, thoughts, commands, paths, outputs or credentials.
        for source, target in (("conversation_id", "cursor.conversation.id"), ("generation_id", "cursor.generation.id"), ("model", "gen_ai.request.model"), ("tool_use_id", "cursor.tool_use.id")):
            value = event.get(source)
            if isinstance(value, str) and 0 < len(value) <= 200:
                attributes[target] = value
        if "cursor.conversation.id" not in attributes:
            raise ValueError("missing correlation")
        if name == "stop" and event.get("status") in ("completed", "aborted", "error"):
            attributes["cursor.stop.status"] = event["status"]
        payload = {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "cursor-cloud-hooks"}}]}, "scopeLogs": [{"scope": {"name": "sazabi.cursor-hooks", "version": "0.1.0"}, "logRecords": [{"timeUnixNano": str(time.time_ns()), "severityNumber": 9, "severityText": "INFO", "body": {"stringValue": "cursor.hook." + name}, "attributes": [{"key": key, "value": {"stringValue": value}} for key, value in attributes.items()]}]}]}]}
        request = urllib.request.Request(endpoint.rstrip("/") + "/v1/logs", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.build_opener(NoRedirect).open(request, timeout=2) as response:
            if response.status not in (200, 202, 204):
                raise ValueError("rejected")
    except Exception:
        # No exception body: network errors can contain the credential-bearing URL.
        sys.stderr.write("Sazabi Cursor telemetry was not delivered.\n")
    sys.stdout.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
