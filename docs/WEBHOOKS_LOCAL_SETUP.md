# Webhook URLs (local development)

The API listens on **port 8000** by default (`python3 -m agent.main`).

## Important: `localhost` is not enough for webhooks

Resend, Cal.com, and Africa’s Talking run on the **public internet**. They **cannot** call `http://localhost:8000/...` on your laptop.

**Use a tunnel** so you get a public HTTPS URL that forwards to `localhost:8000`:

```bash
ngrok http 8000
```

Copy the **Forwarding** HTTPS URL (example: `https://abc123.ngrok-free.app`). That value is your **`WEBHOOK_PUBLIC_BASE`** below.

---

## URLs to register (copy-paste)

Replace `WEBHOOK_PUBLIC_BASE` with your ngrok URL **without** a trailing slash.

| Integration        | Method | Webhook URL to paste |
|--------------------|--------|----------------------|
| **Resend**         | `POST` | `WEBHOOK_PUBLIC_BASE/webhooks/email` |
| **Cal.com**        | `POST` | `WEBHOOK_PUBLIC_BASE/webhooks/cal` |
| **Africa’s Talking** | `POST` | `WEBHOOK_PUBLIC_BASE/webhooks/sms` |
| **HubSpot**        | —      | *See [HubSpot](#hubspot) — this repo has no inbound HubSpot webhook route.* |

### Example (ngrok)

If ngrok shows `https://alpine-mole-12.ngrok-free.app`:

- Resend: `https://alpine-mole-12.ngrok-free.app/webhooks/email`
- Cal.com: `https://alpine-mole-12.ngrok-free.app/webhooks/cal`
- Africa’s Talking: `https://alpine-mole-12.ngrok-free.app/webhooks/sms`

### Local-only paths (for your own tests with `curl`)

Base: `http://127.0.0.1:8000`

- Email: `http://127.0.0.1:8000/webhooks/email`
- Cal: `http://127.0.0.1:8000/webhooks/cal`
- SMS: `http://127.0.0.1:8000/webhooks/sms`

---

## Resend

1. [Resend Dashboard](https://resend.com) → **Webhooks** → **Add endpoint**.
2. **URL:** `WEBHOOK_PUBLIC_BASE/webhooks/email`
3. Subscribe to events you need (at minimum **`email.replied`** if you want reply handling; the app dispatches `lead.email_replied` for that type).
4. Copy the **signing secret** into `.env` as **`RESEND_WEBHOOK_SECRET`** (Svix format, often starts with `whsec_`).
5. Redeploy/restart the API after updating `.env`.

**Note:** If `RESEND_WEBHOOK_SECRET` is empty, the code may skip signature verification (dev-only); set the secret for anything resembling production.

---

## Cal.com

1. Cal.com (cloud or self-hosted) → **Settings** → **Developer** → **Webhooks** (wording varies by version).
2. **Subscriber URL:** `WEBHOOK_PUBLIC_BASE/webhooks/cal`
3. Enable events for **booking created** (payload must include `triggerEvent` / booking payload; this app handles `BOOKING_CREATED` in `agent/webhooks/cal_webhook.py`).
4. If Cal asks for a **secret**, store it in **`CALCOM_WEBHOOK_SECRET`** in `.env`.  
   *The current handler does not verify the secret in code; you can add verification later if Cal sends a signature header.*

---

## Africa’s Talking

1. [Africa’s Talking](https://account.africastalking.com) → your **sandbox** app → **SMS** → set the **callback / webhook URL** for **incoming messages** (exact label varies).
2. **URL:** `WEBHOOK_PUBLIC_BASE/webhooks/sms`
3. The handler expects **form fields**: `from`, `to`, `text`, `id`, optional `linkId` (`agent/webhooks/sms_webhook.py`). If the dashboard offers “JSON” vs “form”, choose the option that matches **application/x-www-form-urlencoded** style fields your integration sends.

---

## HubSpot

**This repository does not expose an inbound HubSpot webhook.** CRM updates are done **outward** from your app with **`HUBSPOT_ACCESS_TOKEN`** (`agent/integrations/hubspot_mcp.py`).

- **Nothing to paste in HubSpot** for webhooks unless you **add a new FastAPI route** (e.g. `/webhooks/hubspot`) and then create a **Subscription** in your HubSpot developer app pointing at `WEBHOOK_PUBLIC_BASE/webhooks/hubspot`.

For the Week 10 demo, configuring **Resend + Cal + Africa’s Talking** URLs as above is enough for the stack described in the challenge.

---

## Quick checklist

1. Start API: `python3 -m agent.main` (port **8000**).
2. Start tunnel: `ngrok http 8000`.
3. Set `WEBHOOK_PUBLIC_BASE` = ngrok HTTPS URL (no trailing `/`).
4. Paste full URLs into Resend, Cal.com, and Africa’s Talking as in the table.
5. Set `RESEND_WEBHOOK_SECRET` (and optional Cal secret) in `.env`, restart API.

Add to `.env` (the app **reads** this and logs URLs on startup):

```env
WEBHOOK_PUBLIC_BASE=https://your-subdomain.ngrok-free.app
```

**From the running API:** open `GET /api/config/webhook-urls` (e.g. `http://localhost:8000/api/config/webhook-urls`) for a JSON copy of the three full URLs. You must still paste them into each provider’s dashboard — the code does not call Resend/Cal/AT APIs to register webhooks automatically.
