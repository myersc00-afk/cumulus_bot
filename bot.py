#!/usr/bin/env python3
"""
Cumulus Linux Troubleshooting Bot
Describe a network problem; Claude investigates via NVUE REST API GET requests.
"""

import os
import json
import sys
import urllib3
import requests
import anthropic

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
SWITCH_HOST = os.environ.get("SWITCH_HOST", "")
SWITCH_USER = os.environ.get("SWITCH_USER", "cumulus")
SWITCH_PASS = os.environ.get("SWITCH_PASS", "")
NVUE_PORT   = os.environ.get("NVUE_PORT", "8765")
NVUE_BASE   = f"https://{SWITCH_HOST}:{NVUE_PORT}/nvue/v1"

client = anthropic.Anthropic()

# ── NVUE GET helper ───────────────────────────────────────────────────────────
def nvue_get(path: str) -> dict:
    url = f"{NVUE_BASE}/{path.lstrip('/')}"
    try:
        resp = requests.get(
            url,
            auth=(SWITCH_USER, SWITCH_PASS),
            verify=False,          # NVUE uses self-signed certs by default
            timeout=10,
            params={"rev": "operational"},  # fetch live state, not staged config
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot reach switch at {SWITCH_HOST}:{NVUE_PORT}"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}

# ── Tool definition ───────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "nvue_get",
        "description": (
            "Make a GET request to the Cumulus Linux NVUE REST API to retrieve "
            "live operational state from the switch. Use this to check interface "
            "status, IP addresses, BGP neighbors, MLAG, EVPN, VXLANs, routing "
            "tables, bridge/VLAN info, system info, and more.\n\n"
            "Common paths:\n"
            "  system                         – hostname, version, uptime\n"
            "  interface                      – all interfaces\n"
            "  interface/{name}               – one interface (swp1, bond0, lo, mgmt)\n"
            "  interface/{name}/ip/address    – IP addresses\n"
            "  interface/{name}/link/stats    – Rx/Tx counters & errors\n"
            "  router/bgp                     – BGP global config & state\n"
            "  router/bgp/neighbor            – all BGP neighbors\n"
            "  vrf                            – all VRFs\n"
            "  vrf/{name}/router/bgp/neighbor – BGP neighbors in a VRF\n"
            "  vrf/{name}/router/rib          – routing table for a VRF\n"
            "  bridge/domain                  – bridge domains (VLANs)\n"
            "  bridge/domain/{name}/mac-table – MAC address table\n"
            "  mlag                           – MLAG (dual-homing) state\n"
            "  evpn                           – EVPN config & state\n"
            "  nve/vxlan                      – VXLAN tunnel info\n"
            "  router/ospf                    – OSPF state\n"
            "  acl                            – ACL rules\n"
            "  platform/environment           – fans, PSUs, temperature\n"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "NVUE API path to query (without leading slash)",
                }
            },
            "required": ["path"],
        },
    }
]

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert Cumulus Linux network troubleshooting assistant \
for Nvidia switches running the NVUE API.

When the user describes a network problem:
1. Identify what layers/features are likely involved (L1, L2 VLANs, L3 routing, BGP, MLAG, EVPN/VXLAN, etc.)
2. Query the switch systematically with nvue_get — start broad, then drill down
3. Show key findings inline as you discover them
4. Clearly state the diagnosis and recommended fix at the end

Be methodical. If a check reveals something unexpected, follow that thread. \
Always explain what each result means in plain language."""

# ── Agentic loop ──────────────────────────────────────────────────────────────
def run_tool(name: str, tool_input: dict) -> str:
    if name == "nvue_get":
        result = nvue_get(tool_input["path"])
        return json.dumps(result, indent=2)
    return json.dumps({"error": f"Unknown tool: {name}"})


def troubleshoot(problem: str) -> None:
    print(f"\n{'─'*60}")
    messages = [{"role": "user", "content": problem}]

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Print text blocks as they arrive
        for block in response.content:
            if block.type == "text":
                print(f"\n{block.text}")

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            print(f"[stop_reason={response.stop_reason}]")
            break

        # Execute tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\n  » GET /nvue/v1/{block.input.get('path', '')}")
                result = run_tool(block.name, block.input)
                # Print a compact preview (first 300 chars) so the user can follow along
                preview = result[:300].replace("\n", " ")
                if len(result) > 300:
                    preview += " …"
                print(f"    {preview}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    if not SWITCH_HOST:
        print("Error: set SWITCH_HOST environment variable (or copy .env.example to .env)")
        sys.exit(1)

    print("Cumulus Linux Troubleshooting Bot")
    print(f"Switch : {SWITCH_HOST}:{NVUE_PORT}")
    print(f"User   : {SWITCH_USER}")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            problem = input("Problem> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not problem:
            continue
        if problem.lower() in ("quit", "exit", "q"):
            break

        troubleshoot(problem)


if __name__ == "__main__":
    main()
