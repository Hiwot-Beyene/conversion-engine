import html
import json
import logging
import re
import time
import httpx
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from agent.config import settings

logger = logging.getLogger(__name__)

_NOTE_JSON_MAX = 55_000


def _hubspot_note_timestamp_ms() -> str:
    """HubSpot notes require hs_timestamp — milliseconds since Unix epoch (string)."""
    return str(int(time.time() * 1000))


def _enrichment_ts_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ICP_SEGMENT_LABELS = {
    "segment_1_series_a_b": "Segment 1 — Recently funded / scaling",
    "segment_2_mid_market_restructure": "Segment 2 — Mid-market / restructuring",
    "segment_3_leadership_transition": "Segment 3 — Leadership transition",
    "segment_4_specialized_capability": "Segment 4 — Specialized capability",
    "abstain": "ICP abstain — exploratory",
}


def _split_contact_name(email: str) -> Tuple[str, str]:
    local = (email or "").split("@")[0].split("+")[0].strip()
    if not local:
        return "Prospect", "Lead"
    parts = re.split(r"[._-]", local, maxsplit=1)
    first = (parts[0][:40] or "Prospect").title()
    last = (parts[1][:40] if len(parts) > 1 else "Lead").title()
    return first, last


# Built-in HubSpot contact properties (work on a fresh portal without custom property setup).
_HUBSPOT_CORE_CONTACT_PROPS = frozenset(
    {
        "email",
        "firstname",
        "lastname",
        "company",
        "website",
        "phone",
        "mobilephone",
        "jobtitle",
        "city",
        "state",
        "zip",
        "country",
        "lifecyclestage",
        "hs_lead_status",
        "hs_language",
        "numemployees",
        "annualrevenue",
        "unsubscribed",
    }
)

# Optional custom properties — enable with HUBSPOT_SYNC_CUSTOM_PROPERTIES after creating them in HubSpot.
_HUBSPOT_ENRICHMENT_CONTACT_PROPS = frozenset(
    {
        "icp_segment",
        "last_orchestrator_action",
        "crunchbase_id",
        "enrichment_timestamp",
        "ai_maturity_score",
        "primary_icp_segment",
        "icp_segment_confidence",
        "prospect_domain",
        "open_engineering_roles",
        "company_sector_snapshot",
        "segment_confidence_numeric",
        "hiring_velocity_label",
    }
)


def _hubspot_prop_allowlist() -> frozenset:
    if settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES:
        return frozenset(_HUBSPOT_CORE_CONTACT_PROPS | _HUBSPOT_ENRICHMENT_CONTACT_PROPS)
    return _HUBSPOT_CORE_CONTACT_PROPS


def _sanitize_contact_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    allowed = _hubspot_prop_allowlist()
    out: Dict[str, Any] = {}
    for key, val in (properties or {}).items():
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            logger.warning("HubSpot: dropping non-scalar property %s", key)
            continue
        if key not in allowed:
            logger.warning(
                "HubSpot: property %s not in allowlist — use Notes API instead; value omitted from PATCH.",
                key,
            )
            continue
        if isinstance(val, bool):
            out[key] = "true" if val else "false"
        elif isinstance(val, (int, float)) and key != "email":
            out[key] = str(val)
        else:
            s = str(val).strip()
            out[key] = s if s else "—"
    return out


def _dropped_contact_properties(properties: Dict[str, Any], safe_props: Dict[str, Any]) -> Dict[str, Any]:
    dropped: Dict[str, Any] = {}
    for key, val in (properties or {}).items():
        if val is None:
            continue
        if key not in safe_props:
            dropped[key] = val
    return dropped


def _invalid_property_names_from_hubspot_body(text: str) -> list[str]:
    """Parse CRM validation errors for PROPERTY_DOESNT_EXIST (portal missing custom field)."""
    names: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return names
    for err in data.get("errors") or []:
        if err.get("code") != "PROPERTY_DOESNT_EXIST":
            continue
        ctx = err.get("context") or {}
        pn = ctx.get("propertyName")
        if isinstance(pn, list):
            names.extend(str(x) for x in pn if x)
        elif pn:
            names.append(str(pn))
    return list(dict.fromkeys(names))


def format_contact_website(domain_or_url: Optional[str]) -> Optional[str]:
    """Public helper for API layer — HubSpot expects a full URL when possible."""
    if not domain_or_url or not str(domain_or_url).strip():
        return None
    s = str(domain_or_url).strip()
    if re.match(r"^https?://", s, re.I):
        return s
    return f"https://{s.lstrip('/')}"


def _website_url(domain_or_url: Optional[str]) -> Optional[str]:
    return format_contact_website(domain_or_url)

class HubSpotError(Exception):
    """Custom exception for HubSpot API failures."""
    pass

class HubSpotClient:
    """
    Production-grade HubSpot integration for syncing lead data and enrichment signals.
    """

    def __init__(self):
        self.access_token = settings.HUBSPOT_ACCESS_TOKEN
        self.base_url = "https://api.hubapi.com"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    @staticmethod
    def contact_properties_from_schema_briefs(
        email: str,
        *,
        company_name: str,
        domain: Optional[str],
        crunchbase_id: str,
        hiring_signal_brief: Dict[str, Any],
        competitor_gap_brief: Optional[Dict[str, Any]] = None,
        sector: str = "",
    ) -> Dict[str, Any]:
        """
        Single PATCH payload: standard + custom string fields. All values are non-empty strings
        where possible so the CRM record stays populated after enrichment.
        """
        now = _enrichment_ts_z()
        fn, ln = _split_contact_name(email)
        hv = hiring_signal_brief.get("hiring_velocity") or {}
        ai_block = hiring_signal_brief.get("ai_maturity") or {}
        jc = int(hv.get("open_roles_today") or 0)
        ai = int(ai_block.get("score") or 0)
        seg = str(hiring_signal_brief.get("primary_segment_match") or "abstain")
        conf = float(hiring_signal_brief.get("segment_confidence") or 0.0)
        pdom = str(hiring_signal_brief.get("prospect_domain") or "").strip() or "unknown.example"
        vel = str(hv.get("velocity_label") or "insufficient_signal")
        cg_sector = ""
        if competitor_gap_brief and competitor_gap_brief.get("prospect_sector"):
            cg_sector = str(competitor_gap_brief.get("prospect_sector"))
        sector_snap = (sector or cg_sector or "—")[:200]
        seg_label = _ICP_SEGMENT_LABELS.get(seg, seg.replace("_", " "))
        job_core = (
            f"Tenacious prospect | {seg_label[:36]} | {jc} public eng. listings | AI~{ai}/3 | {vel[:24]}"
        )
        rollup = (
            f"{job_core} | ICP_key:{seg[:28]} | conf:{conf:.0%} | dom:{pdom[:40]} | "
            f"sector:{sector_snap[:40]} | CB:{str(crunchbase_id)[:20]}"
        )[:255]
        jobtitle = rollup if not settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES else (job_core[:250])

        out: Dict[str, Any] = {
            "firstname": fn,
            "lastname": ln,
            "company": (company_name or "—")[:255],
            "website": _website_url(domain) or "https://unknown.example",
            "jobtitle": jobtitle,
            "lifecyclestage": "lead",
        }
        if settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES:
            out.update(
                {
                    "enrichment_timestamp": now,
                    "icp_segment": seg_label[:255],
                    "primary_icp_segment": seg[:128],
                    "icp_segment_confidence": f"{conf:.4f}",
                    "segment_confidence_numeric": f"{conf:.4f}",
                    "prospect_domain": pdom[:255],
                    "open_engineering_roles": str(jc),
                    "ai_maturity_score": str(ai),
                    "crunchbase_id": str(crunchbase_id)[:128],
                    "last_orchestrator_action": f"enrich_complete:{now}",
                    "company_sector_snapshot": sector_snap,
                    "hiring_velocity_label": vel[:120],
                }
            )
        return out

    @staticmethod
    def format_enrichment_briefs_note_html(
        hiring_signal_brief: Dict[str, Any],
        competitor_gap_brief: Dict[str, Any],
    ) -> str:
        """CRM note: schema-aligned JSON instances (truncated) for operators."""
        ts = _enrichment_ts_z()
        try:
            hj = json.dumps(hiring_signal_brief, indent=2, default=str)
        except (TypeError, ValueError):
            hj = str(hiring_signal_brief)
        try:
            cj = json.dumps(competitor_gap_brief, indent=2, default=str)
        except (TypeError, ValueError):
            cj = str(competitor_gap_brief)
        hj = hj[:_NOTE_JSON_MAX]
        cj = cj[:_NOTE_JSON_MAX]
        return (
            f"<p><b>Tenacious enrichment — {html.escape(ts)}</b></p>"
            "<p><b>Hiring signal brief</b> (JSON Schema instance)</p>"
            f"<pre style='white-space:pre-wrap'>{html.escape(hj)}</pre>"
            "<p><b>Competitor gap brief</b> (JSON Schema instance)</p>"
            f"<pre style='white-space:pre-wrap'>{html.escape(cj)}</pre>"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, HubSpotError)),
        reraise=True
    )
    async def create_or_update_contact(self, email: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Idempotent contact creation/update in HubSpot.
        """
        url = f"{self.base_url}/crm/v3/objects/contacts"
        
        # HubSpot expects search before update for clean state, 
        # but we can use the batch upsert or patch if we have the ID.
        # Here we'll use a search followed by create or update.
        
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        search_payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email
                }]
            }]
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.post(search_url, headers=self.headers, json=search_payload)
            if search_resp.status_code != 200:
                raise HubSpotError(f"HubSpot search HTTP {search_resp.status_code}: {search_resp.text}")
            search_data = search_resp.json()
            if not isinstance(search_data, dict):
                raise HubSpotError("HubSpot search returned non-object JSON")

            safe_props = dict(_sanitize_contact_properties(properties))
            dropped = _dropped_contact_properties(properties, safe_props)
            hubspot_rejected: Dict[str, Any] = {}

            is_update = search_data.get("total", 0) > 0
            contact_id_for_update = str(search_data["results"][0]["id"]) if is_update else ""

            resp: Optional[httpx.Response] = None
            for attempt in range(16):
                if is_update:
                    if not safe_props:
                        raise HubSpotError(
                            "HubSpot contact update has no valid properties left after portal validation."
                        )
                    update_url = f"{self.base_url}/crm/v3/objects/contacts/{contact_id_for_update}"
                    resp = await client.patch(
                        update_url, headers=self.headers, json={"properties": safe_props}
                    )
                else:
                    create_body = {**safe_props, "email": email}
                    resp = await client.post(url, headers=self.headers, json={"properties": create_body})

                if resp.status_code in (200, 201):
                    break

                if resp.status_code == 400:
                    bad = _invalid_property_names_from_hubspot_body(resp.text)
                    if bad:
                        for n in bad:
                            if n in safe_props:
                                hubspot_rejected[n] = safe_props.pop(n)
                        logger.warning(
                            "HubSpot rejected properties (missing in portal); retrying without: %s",
                            bad,
                        )
                        if attempt >= 15:
                            raise HubSpotError(f"HubSpot sync HTTP 400 after retries: {resp.text}")
                        continue
                    raise HubSpotError(f"HubSpot sync HTTP {resp.status_code}: {resp.text}")

                raise HubSpotError(f"HubSpot sync HTTP {resp.status_code}: {resp.text}")

            if resp is None or resp.status_code not in (200, 201):
                raise HubSpotError("HubSpot sync failed with no response")

            payload = resp.json()
            contact_id = (
                payload.get("id")
                or (payload.get("data") or {}).get("id")
                or (contact_id_for_update if is_update else None)
                or search_data.get("results", [{}])[0].get("id")
            )
            note_parts: list[str] = []
            if dropped and contact_id:
                dropped_text = "<br/>".join(f"<b>{k}</b>: {str(v)[:300]}" for k, v in dropped.items())
                note_parts.append(
                    "<p><b>Omitted from PATCH (allowlist)</b></p>" f"<p>{dropped_text}</p>"
                )
            if hubspot_rejected and contact_id:
                rej = "<br/>".join(
                    f"<b>{k}</b>: {str(v)[:300]}" for k, v in hubspot_rejected.items()
                )
                note_parts.append(
                    "<p><b>Rejected by HubSpot — enable HUBSPOT_SYNC_CUSTOM_PROPERTIES and create these fields, "
                    "or rely on jobtitle + notes</b></p>"
                    f"<p>{rej}</p>"
                )
            if note_parts and contact_id:
                await self._create_note_engagement(str(contact_id), "".join(note_parts))

            return {"success": True, "data": payload}

    async def get_contact_for_dashboard(self, email: str) -> Optional[Dict[str, Any]]:
        """Returns contact id + properties for operator dashboard (demo / ops)."""
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        properties = [
            "email",
            "firstname",
            "lastname",
            "company",
            "website",
            "jobtitle",
            "lifecyclestage",
            "phone",
            "city",
            "state",
            "country",
            "hs_lastmodifieddate",
            "lastmodifieddate",
        ]
        if settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES:
            properties.extend(
                [
                    "enrichment_timestamp",
                    "icp_segment",
                    "primary_icp_segment",
                    "crunchbase_id",
                    "ai_maturity_score",
                    "prospect_domain",
                    "open_engineering_roles",
                ]
            )
        search_payload = {
            "filterGroups": [
                {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
            ],
            "properties": properties,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(search_url, headers=self.headers, json=search_payload)
        if resp.status_code != 200:
            logger.error("HubSpot search failed: %s", resp.text)
            return None
        data = resp.json()
        if data.get("total", 0) < 1:
            return None
        row = data["results"][0]
        props = row.get("properties") or {}
        required = (
            "email",
            "firstname",
            "lastname",
            "company",
            "website",
            "jobtitle",
            "lifecyclestage",
            "hs_lastmodifieddate",
            "enrichment_timestamp",
        )
        missing = [k for k in required if not (props.get(k) or "").strip()]
        modified_raw = props.get("hs_lastmodifieddate") or props.get("lastmodifieddate")
        recency_seconds = None
        try:
            if modified_raw:
                dt = datetime.fromisoformat(str(modified_raw).replace("Z", "+00:00"))
                recency_seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        except Exception:
            recency_seconds = None
        current = recency_seconds is not None and recency_seconds <= 300
        demo_properties = {
            "email": props.get("email") or email,
            "firstname": props.get("firstname") or "Synthetic",
            "lastname": props.get("lastname") or "Prospect",
            "company": props.get("company") or "Unknown company",
            "website": props.get("website") or "https://unknown.example",
            "jobtitle": props.get("jobtitle") or "Unknown title",
            "lifecyclestage": props.get("lifecyclestage") or "lead",
            "hs_lastmodifieddate": props.get("hs_lastmodifieddate") or props.get("lastmodifieddate") or "",
            "enrichment_timestamp": props.get("enrichment_timestamp") or "",
            "icp_segment": props.get("icp_segment") or "",
            "prospect_domain": props.get("prospect_domain") or "",
        }
        return {
            "id": row.get("id"),
            "properties": props,
            "demo_properties": demo_properties,
            "updated_at": row.get("updatedAt"),
            "created_at": row.get("createdAt"),
            "demo_health": {
                "required_non_null": len(missing) == 0,
                "missing_fields": missing,
                "enrichment_timestamp_current": current,
                "seconds_since_update": recency_seconds,
            },
        }

    async def sync_enrichment_data(self, email: str, enrichment_signals: Dict[str, Any]):
        """
        Orchestrator / DB payload path: PATCH contact with non-null enrichment fields + note.
        """
        root = enrichment_signals.get("signals") or enrichment_signals
        cb_block = root.get("crunchbase") or {}
        cb_data = cb_block.get("data") or {}

        def _safe_float(val: Any, default: float = 0.0) -> float:
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        employee_count = int(_safe_float(cb_data.get("employee_count"), 0.0))
        funding_amount = _safe_float(cb_data.get("funding_amount_usd"), 0.0)

        icp_fit = "Low Fit"
        if employee_count > 500:
            icp_fit = "Enterprise Fit"
        elif employee_count > 50 or funding_amount > 1000000:
            icp_fit = "Mid-Market / High Fit"

        sector = str(cb_data.get("sector") or "—")[:200]
        now = _enrichment_ts_z()
        fn, ln = _split_contact_name(email)
        company = str(cb_data.get("name") or enrichment_signals.get("company_name") or "—")[:255]
        cb_key = str(cb_data.get("crunchbase_id") or cb_data.get("id") or "—")[:128]
        pdom = str(cb_data.get("domain") or "unknown.example")[:255]

        jt = (
            f"Tenacious pipeline | {icp_fit} | {sector[:56]} | emp~{employee_count} | "
            f"fund~{funding_amount:.0f} | CB:{cb_key[:24]} | {pdom[:40]}"
        )[:255]
        properties: Dict[str, Any] = {
            "firstname": fn,
            "lastname": ln,
            "company": company,
            "website": _website_url(cb_data.get("domain")) or "https://unknown.example",
            "lifecyclestage": "lead",
            "jobtitle": jt,
        }
        if settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES:
            properties.update(
                {
                    "icp_segment": icp_fit[:255],
                    "primary_icp_segment": icp_fit[:128],
                    "icp_segment_confidence": "0.5000",
                    "segment_confidence_numeric": "0.5000",
                    "enrichment_timestamp": now,
                    "prospect_domain": pdom,
                    "open_engineering_roles": "0",
                    "ai_maturity_score": "0",
                    "crunchbase_id": cb_key,
                    "last_orchestrator_action": f"pipeline_sync:{now}",
                    "company_sector_snapshot": sector,
                    "hiring_velocity_label": "insufficient_signal",
                }
            )

        lay_block = root.get("layoffs") or {}
        lay_data = lay_block.get("data") or {}
        note_lines = [
            f"<p><b>Tenacious enrichment</b> — {html.escape(now)}</p>",
            f"<p><b>ICP fit (firmographic heuristic):</b> {html.escape(icp_fit)}</p>",
            f"<p><b>Sector:</b> {html.escape(sector)}</p>",
        ]
        if lay_data.get("has_layoffs"):
            note_lines.append("<p><b>Workforce signal:</b> matching row in public snapshot.</p>")

        ai_block = enrichment_signals.get("ai_maturity") or {}
        if isinstance(ai_block, dict) and ai_block.get("integer_score") is not None:
            ai_s = str(int(ai_block["integer_score"]))
            if settings.HUBSPOT_SYNC_CUSTOM_PROPERTIES:
                properties["ai_maturity_score"] = ai_s
            note_lines.append(
                f"<p><b>AI maturity (public-signal estimate):</b> {ai_block['integer_score']}/3</p>"
            )

        try:
            result = await self.create_or_update_contact(email, properties)
        except HubSpotError as e:
            logger.error("sync_enrichment_data HubSpot error: %s", e)
            return {"success": False, "error": str(e)}
        if result.get("success"):
            cid = (result.get("data") or {}).get("id")
            if cid:
                await self._create_note_engagement(str(cid), "".join(note_lines))
        return result

    async def _create_note_engagement(self, contact_id: str, html_body: str) -> Dict[str, Any]:
        """Attach a CRM note — works on standard sandboxes without custom contact properties."""
        note_url = f"{self.base_url}/crm/v3/objects/notes"
        note_payload = {
            "properties": {
                "hs_note_body": html_body,
                "hs_timestamp": _hubspot_note_timestamp_ms(),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 202,
                        }
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(note_url, headers=self.headers, json=note_payload)
        if resp.status_code not in (200, 201):
            logger.error("HubSpot note create failed: %s", resp.text)
            return {"success": False, "error": resp.text}
        return {"success": True, "data": resp.json()}

    async def append_note_for_contact_email(self, email: str, html_body: str) -> Dict[str, Any]:
        """Adds a second note (e.g. competitor gap) without relying on custom contact properties."""
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        search_payload = {
            "filterGroups": [
                {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
            ]
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            search_resp = await client.post(search_url, headers=self.headers, json=search_payload)
        data = search_resp.json()
        if data.get("total", 0) < 1:
            logger.warning("append_note: no contact for %s", email)
            return {"success": False, "error": "Contact not found"}
        cid = str(data["results"][0]["id"])
        return await self._create_note_engagement(cid, html_body)

    async def log_event(self, email: str, event_type: str, body: str) -> Dict[str, Any]:
        """
        Logs a communication event (email, SMS, reply) as a HubSpot note.
        """
        # 1. Get contact ID
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        search_payload = {
            "filters": [{"propertyName": "email", "operator": "EQ", "value": email}]
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.post(search_url, headers=self.headers, json={"filterGroups": [{"filters": search_payload["filters"]}]})
            search_data = search_resp.json()
            
            if search_data.get("total", 0) == 0:
                logger.warning(f"Cannot log event: Contact {email} not found in HubSpot.")
                return {"success": False, "error": "Contact not found"}
            
            contact_id = search_data["results"][0]["id"]
            
            # 2. Create Note (Engagement)
            note_url = f"{self.base_url}/crm/v3/objects/notes"
            note_payload = {
                "properties": {
                    "hs_note_body": f"<b>[{event_type.upper()}]</b><br/>{body}",
                    "hs_timestamp": _hubspot_note_timestamp_ms(),
                },
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 202 # Note to Contact
                            }
                        ]
                    }
                ]
            }
            
            resp = await client.post(note_url, headers=self.headers, json=note_payload)
            if resp.status_code not in (200, 201):
                logger.error(f"Failed to log HubSpot event: {resp.text}")
                return {"success": False, "error": resp.text}
                
            return {"success": True, "data": resp.json()}

# Singleton instance
hubspot_client = HubSpotClient()
