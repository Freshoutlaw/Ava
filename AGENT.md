# AGENT.md — Ava
> Single source of truth for this project. Every build session starts here.

---

## Identity

| Field | Value |
|---|---|
| **Name** | Ava |
| **Tagline** | My AI executive assistant — your personal partner in business and life, proactively managing your finances, streamlining your daily operations, and securing your tech — so you stay focused, empowered, and always one step ahead. |
| **Audience** | Just me (single-user; per-user state not required in early tiers, but keep it in mind) |
| **Personality** | Warm and plain-spoken. Brief. Never preachy. Talks like a sharp, trusted colleague — not a corporate chatbot. Consistent across text, voice, and proactive messages. |

---

## First three capabilities (Tier 2 tools)

These become the first tools in the registry and the first test cases.

1. **Business growth & finance** — help drive toward the first $500K revenue milestone by year-end: track metrics, surface opportunities, flag risks, help plan next moves.
2. **Life organisation & social skills** — keep life organised and build networking, communication, and negotiation capabilities: draft outreach, prep for conversations, debrief after them.
3. **Adaptive assistant core** — constantly learn preferences and working style, surface the most relevant help at the right moment, get better with every interaction.

---

## Stack

| Decision | Choice | Notes |
|---|---|---|
| **Language / runtime** | Python 3 | stdlib + small well-known packages only. Keep the harness readable. |
| **Model provider** | Groq (current) → Anthropic Claude (later) | Provider behind a thin seam — swap by changing one function only. |
| **Speech-to-text** | Deepgram | Fast, streaming, accurate. Behind its own seam. Key in env var. |
| **Text-to-speech** | ElevenLabs | Natural voice, streaming audio. Behind its own seam. Voice TBD before Tier 3. |
| **Deployment target** | Always-on server from day one | Runs unattended on a server without code changes. |
| **Voice input mode** | Push-to-talk first (Tier 3), wake word later | Text interface always stays alive. |

---

## Secrets & environment

All secrets in `.env` (git-ignored from commit 1). Never in source code.

```
GROQ_API_KEY=           # current
# ANTHROPIC_API_KEY=    # uncomment when switching to Claude
# DEEPGRAM_API_KEY=
# ELEVENLABS_API_KEY=
# ELEVENLABS_VOICE_ID=
```

---

## Confirmation gate — never without asking

- Send any message (text, email, DM, post)
- Spend money / initiate any financial transaction
- Delete data (files, records, history)
- Change settings (system, app, account)
- Commit to git or push code
- Post publicly (social, forum, blog)
- Leak or share sensitive / private information or data

Gate applies to spoken turns, typed turns, and heartbeat-initiated actions alike.

---

## Proactive behaviour

Yes — quiet by default. Ava earns interruptions, doesn't assume them.

- Most checks → calm log only
- Genuine time-sensitive insight → surface once
- Non-urgent notices → hold for waking hours (configurable)
- Missed notices → held and shown on return, never lost
- Every surfaced item is dismissible

---

## Tier build order

| Tier | What | Done when |
|---|---|---|
| **0** | Interview + spec | ✅ |
| **1** | Text conversation loop | Type, get reply, remembers 3 turns back |
| **2** | Tool registry + first tools | Ava calls a tool and weaves result into reply |
| **3** | Voice (push-to-talk) | Hold key, speak, hear answer |
| **4** | Persistent memory | Tell her something, restart, she knows it |
| **5** | Heartbeat (proactive loop) | She surfaces a check without being spoken to |
| **6** | Rails (gate, log, kill switch, config) | Consequential action stops and asks |

---

## Architectural rules

1. One shared agent core — never fork for voice vs text.
2. Provider behind a seam — one function, nothing else touches the SDK.
3. Stream everywhere — voice starts before reply is complete.
4. Secrets in env only — never in code or logs.
5. Tool registry is the extension point — new capability = one tool, never edit the loop.
6. Memory is data, not commands — never bypasses the confirmation gate.
7. Keep the text path alive forever.
8. Fail gracefully — clear message, clean prompt, no stack traces shown.

---

## Open decisions

- [ ] ElevenLabs voice ID (resolve before Tier 3)
- [ ] Server hosting choice (resolve before Tier 5)
- [ ] Quiet hours window (default 22:00–07:00)
- [ ] First business metrics to track (Tier 2 tool #1)
- [ ] Switch GROQ_API_KEY → ANTHROPIC_API_KEY when ready

---

*Last updated: Tier 0 complete. Next: Tier 1 — text conversation loop.*
