# patterns.json Reference

This document describes the `patterns.json` file used by **vpn-abuse-bot** and consumed by **remnanode-watchdog** nodes.
The bot serves this file via `GET /api/patterns`; each watchdog node polls it periodically and compiles the patterns into its detection engine.

---

## File location

| Setting              | Default               |
|----------------------|-----------------------|
| `PATTERNS_FILE`      | `/data/patterns.json` |
| `PATTERNS_CACHE_SECONDS` | `5`              |

Mount the file into the bot container (read-only is fine):

```yaml
volumes:
  - ./data:/data:ro
```

---

## Top-level structure

```jsonc
{
  "patterns": [
    { /* pattern object */ },
    { /* pattern object */ }
  ]
}
```

The root object has a single key `patterns` — an array of pattern objects.

---

## Pattern object

Every pattern object represents one detection rule.
Below is a complete field reference.

### Core fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | **yes** | — | Unique identifier for this pattern. Used to match state across config reloads — if you rename an `id`, accumulated counters for the old ID are lost. |
| `enabled` | bool | **yes** | — | Set to `false` to disable the pattern without removing it. |

### Line matching

These fields decide whether a log line is relevant to this pattern.
Both checks must pass (AND logic); `matchRegex` is optional.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mustContain` | string[] | **yes** | — | **All** strings in this array must be present in the log line (substring match, case-sensitive). This is a fast pre-filter evaluated before any regex. |
| `matchRegex` | string | no | `""` (skip) | An optional regex applied after `mustContain`. The line must match this regex to proceed. Empty string or omitted means no regex check. |

**Example log line:**

```
2026/03/25 22:28:39.840948 from 92.36.91.157:4148 accepted tcp:www.google.com:443 [US_upgr-2 >> DIRECT] email: 1178372
```

To match lines that were accepted and routed to BLOCK:

```json
"mustContain": ["accepted", "BLOCK]", "email:"],
"matchRegex": "\\[[^\\]]+\\s(?:->|>>)\\s*BLOCK\\]"
```

### User identification

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `userIdType` | string | no | `"EMAIL"` | How to identify the user that generated the log line. Possible values below. |

| Value | Behaviour |
|-------|-----------|
| `EMAIL` | Extract user ID from the log line using the `extract` rule (see below). Typically an email address or numeric account ID. |
| `IP` | Use the source IPv4 address parsed from the `from <ip>:<port>` portion of the log line. No `extract` rule is needed. Private/invalid IPs are silently skipped. |
| `IPorEMAIL` | Extract **both** the email (`extract` rule) and the source IP from each log line, then track them as **independent counters**. If the email counter reaches the threshold first the alert fires with the email as `userId`; if the IP counter reaches first, the alert fires with the IP. **Only one notification is sent per abuse burst** — when one counter fires, the partner counter is placed into cooldown so it does not produce a duplicate alert. This catches abuse that spans multiple emails from one IP, or multiple IPs for one email. |

### Extract rule (`extract`)

Tells the watchdog how to pull the user identifier out of a log line.
**Required** when `userIdType` is `EMAIL` or `IPorEMAIL`. Ignored when `userIdType` is `IP`.

```json
"extract": {
  "type": "after",
  "after": "email:",
  "until": ""
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"after"` or `"regex"`. |
| `after` | string | *(type=after)* Marker string. The user ID is the token immediately after this marker. |
| `until` | string | *(type=after)* Optional stop marker. If empty, extraction stops at the next whitespace. |
| `regex` | string | *(type=regex)* Regular expression with at least one capture group. |
| `group` | int | *(type=regex)* Which capture group to use (1-based). |

**`type: "after"` example** — extract everything after `email:` up to the next whitespace:

```json
{ "type": "after", "after": "email:", "until": "" }
```

Given `... email: 1178372 ...` this yields `1178372`.

**`type: "regex"` example** — extract an email address with a regex:

```json
{ "type": "regex", "regex": "user=([\\w.+-]+@[\\w.-]+)", "group": 1 }
```

### Destination extract rule (`destExtract`)

Optional. When provided, enables **identical-request detection**: the watchdog tracks events per *(user, destination)* pair rather than per user alone.

The format is identical to `extract`:

```json
"destExtract": {
  "type": "after",
  "after": "accepted ",
  "until": " "
}
```

Given the log line:

```
2026/03/25 22:28:39.840948 from 92.36.91.157:4148 accepted tcp:www.google.com:443 [US_upgr-2 >> DIRECT] email: 1178372
```

This extracts `tcp:www.google.com:443` as the destination. If the same user sends 100 requests to this exact destination within the configured window, the pattern fires.

Without `destExtract`, requests to *any* destination are counted together. With it, only requests to the *same* destination are counted.

When the pattern triggers, the webhook payload includes a `destination` field with the matched value.

### Threshold & timing

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `threshold` | int | **yes** | `1` | Number of matching events within the window required to trigger an alert. |
| `windowSeconds` | int | **yes** | `60` | Sliding time window in seconds. The watchdog checks whether the last `threshold` events all fit within this window. |
| `cooldownSeconds` | int | **yes** | `0` | Minimum seconds between two alerts for the **same user** (and same destination, if `destExtract` is set). Prevents alert spam. Set to `0` to alert on every threshold breach. |
| `burstAllowance` | int | no | `0` | Number of threshold breaches to **absorb silently** before actually firing an alert. Filters out short, one-off traffic spikes. See detailed explanation below. |

**How counting works:**

The watchdog keeps a circular buffer of the last `threshold` timestamps per tracking key. When the buffer is full and the oldest timestamp is within `windowSeconds` of now, the threshold is met. If `cooldownSeconds` has elapsed since the last alert for this key, an alert fires.

**How `burstAllowance` works:**

When `burstAllowance` is `0` (default), the alert fires on the very first threshold breach — the existing behaviour.

When `burstAllowance` is set to **N** (e.g. `2`), the first N threshold breaches are silently absorbed. Each absorbed breach still starts the cooldown timer, so consecutive bursts must be cooldown-separated events. Only on the **(N+1)th** breach does an actual alert fire.

| burstAllowance | Behaviour |
|----------------|-----------|
| `0` | Alert fires immediately when threshold is met (default). |
| `1` | First burst absorbed; alert fires on the 2nd. |
| `2` | First two bursts absorbed; alert fires on the 3rd. |

The burst counter **resets automatically** if the user goes quiet for `cooldownSeconds × (burstAllowance + 1)`. This means old bursts from hours ago don't count toward the current cycle.

**Example** — tolerate one short spike but alert on sustained abuse:

```json
"threshold": 100,
"windowSeconds": 60,
"cooldownSeconds": 1800,
"burstAllowance": 1
```

A user who triggers 100 requests in 60 seconds once gets no notification. If they do it again after the 30-minute cooldown, the alert fires.

### Enforcement

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `banType` | string | no | `"WEBHOOK"` | What happens when the pattern triggers. |

| Value | Behaviour |
|-------|-----------|
| `WEBHOOK` | Send an alert to the bot via webhook. No node-side firewall action. The bot notifies the admin in Telegram with action buttons (Details / Ban / Ignore). |
| `FIRST_IP_WEBHOOK_AFTER` | **First** block the source IP on the node firewall (nftables), **then** send the webhook. The webhook payload includes `bannedIp`, `firewallType`, `firewallOk`, and `firewallError` fields. Use this for high-severity patterns where you want immediate automated IP blocking. |

### Server targeting

Control which nodes apply this pattern. Useful when you have multiple VPN nodes polling the same patterns file but want certain rules only on specific servers.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `serverPolicy` | string | no | `"DEFAULT_APPLY"` | Base policy for this pattern. |
| `serverExceptions` | string[] | no | `[]` | List of node IPv4 addresses that are exceptions to the policy. |

| Policy | Behaviour |
|--------|-----------|
| `DEFAULT_APPLY` | Pattern is active on **all** nodes **except** those listed in `serverExceptions`. |
| `DEFAULT_SKIP` | Pattern is **disabled** on all nodes **except** those listed in `serverExceptions`. |

**Example** — enable a pattern only on node `203.0.113.10`:

```json
"serverPolicy": "DEFAULT_SKIP",
"serverExceptions": ["203.0.113.10"]
```

### Limits

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `maxTrackedUsers` | int | no | `20000` | Maximum number of unique tracking keys (user or user+destination) held in memory per pattern. When the limit is reached, new users are silently ignored until old entries expire. Protects node memory. |
| `includeSample` | bool | no | `false` | If `true`, the triggering log line is included in the webhook payload as `sample` (truncated to 600 chars in the Telegram message). Useful for debugging, but increases payload size. |

---

## Complete examples

### 1. Email-based block detection

Alert when a single email triggers 60 blocked requests in 30 seconds. Active on all nodes except `203.0.113.10`. Admin gets a Telegram notification with ban buttons.

```json
{
  "id": "BLOCK_60t_in_30s",
  "enabled": true,
  "serverPolicy": "DEFAULT_APPLY",
  "serverExceptions": ["203.0.113.10"],
  "banType": "WEBHOOK",
  "userIdType": "EMAIL",
  "mustContain": ["accepted", "BLOCK]", "email:"],
  "matchRegex": "\\[[^\\]]+\\s(?:->|>>)\\s*BLOCK\\]",
  "extract": { "type": "after", "after": "email:", "until": "" },
  "threshold": 60,
  "windowSeconds": 30,
  "cooldownSeconds": 1800,
  "maxTrackedUsers": 20000,
  "includeSample": false
}
```

### 2. IP-based block detection with automatic firewall ban

Same detection logic, but identified by source IP and with automatic nftables ban on the node. Only active on node `203.0.113.10`.

```json
{
  "id": "BLOCK_60t_in_30s_IP",
  "enabled": true,
  "serverPolicy": "DEFAULT_SKIP",
  "serverExceptions": ["203.0.113.10"],
  "banType": "FIRST_IP_WEBHOOK_AFTER",
  "userIdType": "IP",
  "mustContain": ["accepted", "BLOCK]"],
  "matchRegex": "\\[[^\\]]+\\s(?:->|>>)\\s*BLOCK\\]",
  "extract": {},
  "threshold": 60,
  "windowSeconds": 30,
  "cooldownSeconds": 1800,
  "maxTrackedUsers": 20000,
  "includeSample": false
}
```

### 3. Identical destination flood detection (IPorEMAIL)

Alert when one user (tracked by both IP and email) makes 100+ requests to the **same destination** within 60 seconds. Catches patterns like a single user hammering `tcp:www.google.com:443` repeatedly.

```json
{
  "id": "IDENTICAL_DEST_100t_in_60s",
  "enabled": true,
  "serverPolicy": "DEFAULT_APPLY",
  "serverExceptions": [],
  "banType": "WEBHOOK",
  "userIdType": "IPorEMAIL",
  "mustContain": ["accepted", "email:"],
  "matchRegex": "",
  "extract": { "type": "after", "after": "email:", "until": "" },
  "destExtract": { "type": "after", "after": "accepted ", "until": " " },
  "threshold": 100,
  "windowSeconds": 60,
  "cooldownSeconds": 1800,
  "maxTrackedUsers": 20000,
  "includeSample": true
}
```

---

## Webhook payload

When a pattern triggers, the watchdog sends a POST to the bot. Here is the full payload shape for reference:

```jsonc
{
  "event": "pattern_match",
  "node": "203.0.113.10",           // node public IPv4 or hostname
  "patternId": "BLOCK_60t_in_30s",
  "userId": "1178372",              // email, account ID, or IP
  "count": 60,
  "windowSeconds": 30,
  "observedAt": "2026-03-25T22:28:39.840948Z",
  "userIdType": "EMAIL",            // EMAIL | IP | IPorEMAIL
  "destination": "tcp:www.google.com:443",  // only when destExtract is configured
  "sample": "full log line…",       // only when includeSample is true

  // Only present when banType = FIRST_IP_WEBHOOK_AFTER:
  "banType": "FIRST_IP_WEBHOOK_AFTER",
  "bannedIp": "92.36.91.157",
  "firewallType": "nftables",
  "firewallOk": true,
  "firewallError": ""
}
```

---

## Tips

- **Start with `includeSample: true`** on new patterns so you can verify matches in Telegram before going hands-off.
- **Use `mustContain` aggressively** — it is a fast substring check and filters out the vast majority of lines before any regex runs.
- **Keep `cooldownSeconds` reasonable** (e.g., 1800 = 30 min) to avoid flooding the Telegram chat.
- **Pattern IDs are stable keys** — the watchdog carries over in-memory counters across config reloads by matching on `id`. Renaming an ID resets its counters.
- **`destExtract` is optional** — only add it when you care about *which* destination is being hit. Without it, all requests from a user are counted together regardless of destination.
- Changes to `patterns.json` are picked up automatically by nodes within `PATTERNS_POLL` seconds (default 60). No restart is needed.
