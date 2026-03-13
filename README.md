# cumulus_bot

A Claude-powered CLI troubleshooting assistant for Nvidia switches running Cumulus Linux. Describe a network problem in plain English and the bot systematically queries the switch's NVUE REST API to diagnose it — no manual CLI needed.

## How it works

1. You describe a problem (e.g. *"BGP session to spine1 keeps flapping"*)
2. Claude reasons about what to investigate and fires targeted GET requests against the NVUE REST API
3. Results are fed back to Claude, which drills deeper until it has a root cause
4. A plain-language diagnosis and recommended fix is printed

Only GET requests are made — the switch state is never modified.

## Requirements

- Python 3.10+
- Cumulus Linux switch with NVUE API enabled (port 8765)
- Anthropic API key

## Setup

```bash
git clone git@github.com:myersc00-afk/cumulus_bot.git
cd cumulus_bot
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your switch details and API key
set -a && source .env && set +a

python3 bot.py
```

## Configuration

| Variable          | Description                          | Default    |
|-------------------|--------------------------------------|------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key             | *(required)* |
| `SWITCH_HOST`     | Switch IP or hostname                | *(required)* |
| `SWITCH_USER`     | NVUE API username                    | `cumulus`  |
| `SWITCH_PASS`     | NVUE API password                    | *(required)* |
| `NVUE_PORT`       | NVUE REST API port                   | `8765`     |

## Usage examples

### BGP troubleshooting
```
Problem> BGP session to 10.0.0.1 is down

  » GET /nvue/v1/system
  » GET /nvue/v1/router/bgp/neighbor
  » GET /nvue/v1/interface/swp1
  » GET /nvue/v1/interface/swp1/link/stats

BGP neighbor 10.0.0.1 is in Idle state. Interface swp1 shows 847 input errors
and the link is bouncing — likely a physical layer issue. Check the cable or
SFP on swp1. Once the link stabilizes, BGP should re-establish automatically.
```

### VLAN / L2 troubleshooting
```
Problem> Hosts in VLAN 100 can't reach each other

  » GET /nvue/v1/bridge/domain
  » GET /nvue/v1/bridge/domain/br_default/vlan
  » GET /nvue/v1/interface/bond0
  » GET /nvue/v1/bridge/domain/br_default/mac-table

VLAN 100 is configured on br_default but bond0 is not a member of that VLAN.
Add VLAN 100 to bond0: `nv set interface bond0 bridge domain br_default vlan 100`
```

### MLAG troubleshooting
```
Problem> One of my MLAG peers shows as inconsistent

  » GET /nvue/v1/mlag
  » GET /nvue/v1/interface/peerlink
  » GET /nvue/v1/interface/peerlink/link/stats

MLAG peer is reachable but shows role conflict — both peers have the same
priority (32768). Set a lower priority on the intended primary:
`nv set mlag priority 1000` then `nv action apply`
```

### EVPN / VXLAN troubleshooting
```
Problem> EVPN type-2 routes not showing up from remote VTEPs

  » GET /nvue/v1/evpn
  » GET /nvue/v1/nve/vxlan
  » GET /nvue/v1/router/bgp/neighbor
  » GET /nvue/v1/vrf/default/router/rib

EVPN address-family is not activated on BGP neighbor 10.10.10.2. The session
is up (Established) but only IPv4 unicast is exchanged. Activate the EVPN
address family: `nv set vrf default router bgp neighbor 10.10.10.2 address-family l2vpn-evpn enable on`
```

### Hardware / environment check
```
Problem> Switch is running hot and I'm seeing unexpected reboots

  » GET /nvue/v1/platform/environment
  » GET /nvue/v1/system

Fan 3 is reporting ABSENT and two PSUs show input voltage below threshold.
Seat Fan 3 and check the power feed to PSU 2. The thermal throttling from
reduced airflow is likely causing the unexpected reboots.
```

## NVUE API paths reference

The bot knows about these paths and will query them as needed:

| Path | What it returns |
|------|----------------|
| `system` | Hostname, version, uptime |
| `interface` | All interfaces |
| `interface/{name}` | Single interface state |
| `interface/{name}/link/stats` | Rx/Tx counters & errors |
| `router/bgp/neighbor` | BGP neighbor table |
| `vrf/{name}/router/rib` | Routing table per VRF |
| `bridge/domain` | Bridge domains & VLANs |
| `bridge/domain/{name}/mac-table` | MAC address table |
| `mlag` | MLAG peer state |
| `evpn` | EVPN config & state |
| `nve/vxlan` | VXLAN tunnel info |
| `router/ospf` | OSPF state |
| `platform/environment` | Fans, PSUs, temperature |

## Notes

- SSL certificate verification is disabled by default (NVUE uses self-signed certs)
- All API calls use `?rev=operational` to fetch live state, not staged config
- The bot uses `claude-opus-4-6` with adaptive thinking for deeper reasoning
