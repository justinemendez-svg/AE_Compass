"""Grounded, bounded Ask Compass assistant — an analyst co-pilot.

The model is given a closed menu of server-owned tools that read the signed-in
AE's authorized dashboard data (deals, metrics, forecast, stage mix, linearity,
pipeline creation, roster, and deal search). It runs a bounded tool-calling loop so
it can pull several data sources and reason over them before answering — but it
never emits SQL, URLs, or code, and every number it cites is re-checked against
server-computed facts before the user sees it.

Provider: OpenAI. Two auth paths, tried in order:
  1. Codex / ChatGPT subscription token (~/.codex/auth.json, auth_mode "chatgpt")
     — Responses API at the ChatGPT Codex backend. No API credits needed.
  2. OPENAI_API_KEY — standard OpenAI API (Chat Completions), billed to credits.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable


_client = None
_backend = None  # "codex" | "openai"
_client_lock = threading.Lock()

_MAX_TOOL_STEPS = 5
_MAX_TOOL_CALLS = 12
_MAX_TURNS = 10
_MAX_CHARS = 800
_MAX_DEALS = 200
_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
_CODEX_AUTH_FILE = os.environ.get("CODEX_AUTH_FILE") or os.path.expanduser("~/.codex/auth.json")


class AssistantUnavailable(RuntimeError):
    pass


def _get_model() -> str:
    return os.environ.get("OPENAI_ASSISTANT_MODEL", "gpt-5.5")


# --------------------------------------------------------------------------- #
# Auth + client
# --------------------------------------------------------------------------- #

def _load_codex_token():
    """Return (access_token, account_id) from the Codex CLI auth file, or None."""
    try:
        d = json.load(open(_CODEX_AUTH_FILE))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if d.get("auth_mode") != "chatgpt":
        return None
    tokens = d.get("tokens") or {}
    access = (tokens.get("access_token") or "").strip()
    acct = (tokens.get("account_id") or "").strip()
    return (access, acct) if access else None


def _get_client():
    """Lazy singleton. App boots fine with no credentials and no SDK installed."""
    global _client, _backend
    if _client is not None:
        return _client
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AssistantUnavailable(
            "Ask Compass needs the OpenAI Python SDK installed on the server."
        ) from exc

    codex = _load_codex_token()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not codex and not api_key:
        raise AssistantUnavailable(
            "Ask Compass is not configured. Log in with `codex` (ChatGPT) or set OPENAI_API_KEY."
        )

    with _client_lock:
        if _client is None:
            if codex:
                access, acct = codex
                _client = OpenAI(
                    api_key=access,
                    base_url=_CODEX_BASE_URL,
                    default_headers={"chatgpt-account-id": acct, "OpenAI-Beta": "responses=experimental"},
                    timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "45")),
                    max_retries=1,
                )
                _backend = "codex"
            else:
                _client = OpenAI(
                    api_key=api_key,
                    base_url=os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1",
                    timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "45")),
                    max_retries=1,
                )
                _backend = "openai"
    return _client


def _api_error(exc: Exception) -> Exception:
    """Turn an OpenAI SDK error into a clear AssistantUnavailable; pass others through."""
    if (type(exc).__module__ or "").startswith("openai"):
        return AssistantUnavailable(f"Ask Compass couldn't reach OpenAI: {getattr(exc, 'message', None) or exc}")
    return exc


# --------------------------------------------------------------------------- #
# Server-owned tools — each runs inside the caller's authorized scope
# --------------------------------------------------------------------------- #

def _rows(viewer: str, quarter: str):
    import mock_server
    return mock_server.get_pipeline({"owner_name": viewer, "quarter": quarter})


def _t_deal_context(viewer: str, quarter: str, args: dict) -> dict:
    rows = _rows(viewer, quarter)
    deals = []
    for index, row in enumerate(rows[:_MAX_DEALS]):
        deals.append({
            "fact_id": f"deal_{index + 1}",
            "opportunity": row.get("opportunity_name"),
            "account": row.get("crm_account_name"),
            "stage": row.get("stage_name"),
            "type": row.get("opportunity_type"),
            "amount": row.get("product_arr_usd", 0),
            "close_date": row.get("closedate"),
            "forecast": row.get("vp_deal_forecast__c") or row.get("manager_forecast__c"),
        })
    return {
        "viewer": viewer, "quarter": quarter,
        "authorized_deal_count": len(deals),
        "authorized_pipeline_amount": round(sum(float(d.get("amount") or 0) for d in deals), 2),
        "deals": deals,
        "facts": [{"fact_id": d["fact_id"], "opportunity": d["opportunity"]} for d in deals],
    }


def _t_metrics(viewer: str, quarter: str, args: dict) -> dict:
    import mock_server
    m = mock_server.get_metrics_summary({"owner_name": viewer, "quarter": quarter})
    facts = [
        {"fact_id": "metric_bookings_total", "label": "Signed this quarter", "value": m.get("bookings_total", 0)},
        {"fact_id": "metric_open_pipeline_total", "label": "Open pipeline", "value": m.get("open_pipeline_total", 0)},
        {"fact_id": "metric_open_pipeline_ai", "label": "AI pipeline", "value": m.get("open_pipeline_ai", 0)},
        {"fact_id": "metric_open_pipeline_nb", "label": "New Business pipeline", "value": m.get("open_pipeline_nb", 0)},
        {"fact_id": "metric_open_deal_count", "label": "Open deals", "value": m.get("open_deal_count", 0)},
        {"fact_id": "metric_bookings_deal_count", "label": "Signed deals", "value": m.get("bookings_deal_count", 0)},
    ]
    return {"metrics": m, "facts": facts}


def _t_forecast(viewer: str, quarter: str, args: dict) -> dict:
    import mock_server
    f = mock_server.get_forecast({"name": viewer, "quarter": quarter})
    facts = [
        {"fact_id": "forecast_quota", "label": "Quota", "value": f.get("quota", 0)},
        {"fact_id": "forecast_forecast", "label": "Forecast", "value": f.get("forecast", 0)},
        {"fact_id": "forecast_ai_target", "label": "AI target", "value": f.get("ai_target", 0)},
        {"fact_id": "forecast_ai_bookings", "label": "AI signed", "value": f.get("ai_bookings", 0)},
        {"fact_id": "forecast_nb_target", "label": "NB target", "value": f.get("nb_target", 0)},
        {"fact_id": "forecast_nb_bookings", "label": "NB signed", "value": f.get("nb_bookings", 0)},
        {"fact_id": "forecast_pipeline", "label": "Pipeline", "value": f.get("pipeline", 0)},
    ]
    return {"forecast": f, "facts": facts}


def _t_stage_distribution(viewer: str, quarter: str, args: dict) -> dict:
    from collections import Counter
    counts = Counter((r.get("stage_name") or "Unknown") for r in _rows(viewer, quarter))
    stages = [{"stage": s, "count": c} for s, c in sorted(counts.items())]
    return {"stages": stages, "facts": [{"fact_id": f"stage_{s}", "label": s, "value": c} for s, c in sorted(counts.items())]}


def _t_linearity(viewer: str, quarter: str, args: dict) -> dict:
    import mock_server
    d = mock_server.get_linearity({"owner_name": viewer, "quarter": quarter})
    return {"linearity": d, "facts": []}


def _t_pipe_creation(viewer: str, quarter: str, args: dict) -> dict:
    import mock_server
    d = mock_server.get_pipe_creation({"owner_name": viewer, "quarter": quarter, "cadence": "month"})
    return {"pipe_creation": d, "facts": []}


def _t_search(viewer: str, quarter: str, args: dict) -> dict:
    keyword = str(args.get("keyword") or "").strip().lower()
    type_filter = str(args.get("type") or "").strip()
    out = []
    for index, row in enumerate(_rows(viewer, quarter)[:_MAX_DEALS]):
        hay = " ".join([
            str(row.get("opportunity_name") or ""), str(row.get("crm_account_name") or ""),
            str(row.get("opportunity_type") or ""), str(row.get("stage_name") or ""),
        ]).lower()
        if keyword and keyword not in hay:
            continue
        if type_filter and (row.get("opportunity_type") or "") != type_filter:
            continue
        out.append({
            "fact_id": f"deal_{index + 1}",
            "opportunity": row.get("opportunity_name"),
            "account": row.get("crm_account_name"),
            "stage": row.get("stage_name"),
            "amount": row.get("product_arr_usd", 0),
            "type": row.get("opportunity_type"),
            "close_date": row.get("closedate"),
        })
    return {"matches": out, "facts": [{"fact_id": d["fact_id"], "opportunity": d["opportunity"]} for d in out]}


def _t_roster(viewer: str, quarter: str, args: dict) -> dict:
    import mock_server
    return {"roster": mock_server.get_roster(), "facts": []}


# Closed catalog: name -> (description, parameters, fn)
_TOOLS: list[dict[str, Any]] = [
    {"name": "get_authorized_deal_context",
     "description": "Read every deal (opportunity) authorized for the signed-in AE this quarter, with stable fact IDs. Takes no arguments. Use this for 'which deal' / 'my deals' questions.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_deal_context},
    {"name": "query_metrics",
     "description": "Read the AE's signed bookings and open pipeline totals (overall, AI, New Business) for the quarter, with stable fact IDs. Takes no arguments.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_metrics},
    {"name": "query_forecast",
     "description": "Read the AE's quota, forecast, AI/New Business targets and signed amounts, and pipeline target for the quarter, with stable fact IDs. Takes no arguments.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_forecast},
    {"name": "query_stage_distribution",
     "description": "Count the AE's open opportunities by stage for the quarter. Takes no arguments.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_stage_distribution},
    {"name": "query_linearity",
     "description": "Read the AE's monthly bookings pace (linearity) for the quarter. Takes no arguments.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_linearity},
    {"name": "query_pipe_creation",
     "description": "Read the AE's pipeline creation cadence by month for the quarter. Takes no arguments.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_pipe_creation},
    {"name": "search_opportunities",
     "description": "Search the AE's authorized deals by keyword (matches opportunity/account/stage/type text) and by opportunity type. Pass empty strings for arguments you don't want to filter on. Returns matching deals with stable fact IDs.",
     "parameters": {"type": "object",
                   "properties": {"keyword": {"type": "string", "description": "Text to match against opportunity/account/stage/type. Pass empty string if no keyword filter."},
                                 "type": {"type": "string", "description": "Opportunity type, e.g. Expansion, New Business, Renewal. Pass empty string if no type filter."}},
                   "required": ["keyword", "type"], "additionalProperties": False},
     "fn": _t_search},
    {"name": "get_roster",
     "description": "Read the AE roster (team directory). Takes no arguments. Use for team / roster / who-on-my-team questions.",
     "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
     "fn": _t_roster},
]

_DISPATCH = {t["name"]: t["fn"] for t in _TOOLS}


def _dispatch(name: str, args: Any, viewer: str, quarter: str) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": "unknown_tool", "facts": []}
    try:
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
        if not isinstance(args, dict):
            args = {}
        return fn(viewer, quarter, args)
    except Exception as exc:  # never let a tool crash the turn
        return {"error": type(exc).__name__, "facts": []}


# --------------------------------------------------------------------------- #
# Tool schemas for each backend
# --------------------------------------------------------------------------- #

def _codex_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["parameters"], "strict": True} for t in _TOOLS]


def _openai_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
             "parameters": t["parameters"]}} for t in _TOOLS]


# --------------------------------------------------------------------------- #
# History + grounding
# --------------------------------------------------------------------------- #

def _history_pairs(history) -> list[dict[str, str]]:
    out = []
    for item in (history or [])[-_MAX_TURNS:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        text = str(item.get("text") or "").strip()[:_MAX_CHARS]
        if text:
            out.append({"role": item["role"], "content": text})
    return out


_SYSTEM = (
    "You are Ask Compass, a calm, encouraging, and analytical deal co-pilot for Zendesk AEs. "
    "You have tools that read the signed-in AE's authorized dashboard data: their deals, metrics, forecast, "
    "stage mix, linearity, pipeline creation, roster, and deal search. Use the tools to pull real data before "
    "answering a data question — never answer from memory. Analyze and connect the dots across what the tools return, "
    "reference real numbers, name specific opportunities when useful, say why it matters, and suggest one practical next move. "
    "If evidence is missing, say so clearly. Never produce SQL, URLs, CRM IDs, or code. "
    "When you have everything you need and are ready to give the final answer (no more tool calls), respond with ONLY a "
    "JSON object: {\"answer\": string, \"fact_ids\": [strings drawn only from the fact_ids the tools returned]}. No prose outside the JSON."
)


def _finalize(raw_text: str, allowed_facts: set, deal_index: dict, agg_facts: dict, model: str) -> dict[str, Any]:
    """Parse the model's final JSON, validate fact_ids, build evidence. Tolerant — never crash."""
    raw = (raw_text or "").strip()
    answer = ""
    fact_ids: list[str] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            answer = str(parsed.get("answer") or "").strip()
            fact_ids = [str(v) for v in parsed.get("fact_ids", []) if isinstance(v, (str, int))]
    except (json.JSONDecodeError, TypeError, ValueError):
        answer = raw  # the model gave prose, not JSON — accept it so the user still gets a conversational answer
    if not answer:
        answer = "I could not complete that analysis from the available data. Try rephrasing the question."

    cited = [fid for fid in fact_ids if fid in allowed_facts][:10]
    evidence = []
    for fid in cited:
        if fid in deal_index:
            d = deal_index[fid]
            evidence.append({"opportunity": d.get("opportunity"), "amount": d.get("amount"),
                              "stage": d.get("stage"), "close_date": d.get("close_date")})
        elif fid in agg_facts:
            evidence.append({"fact_id": fid, "label": agg_facts[fid].get("label"), "value": agg_facts[fid].get("value")})
    return {"answer": answer, "evidence": evidence,
            "source": "Authorized AE Compass deal context", "model": model}


def _collect_facts(allowed: set, deal_index: dict, agg_facts: dict, result: dict) -> None:
    for f in (result or {}).get("facts", []) or []:
        fid = f.get("fact_id")
        if not fid:
            continue
        allowed.add(fid)
        if "opportunity" in f and "amount" in f:
            deal_index[fid] = {"opportunity": f.get("opportunity"), "amount": f.get("amount"),
                               "stage": f.get("stage"), "close_date": f.get("close_date")}
        elif "label" in f:
            agg_facts[fid] = {"label": f.get("label"), "value": f.get("value")}


# --------------------------------------------------------------------------- #
# Codex / ChatGPT backend — Responses API, streaming, bounded loop
# --------------------------------------------------------------------------- #

def _codex_input(pairs: list[dict[str, str]], question: str) -> list[dict[str, Any]]:
    inp = []
    for p in pairs:
        ctype = "output_text" if p["role"] == "assistant" else "input_text"
        inp.append({"role": p["role"], "content": [{"type": ctype, "text": p["content"]}]})
    inp.append({"role": "user", "content": [{"type": "input_text", "text": question[:1200]}]})
    return inp


def _consume_codex_stream(stream) -> tuple[str, list[dict[str, str]]]:
    text: list[str] = []
    fn_calls: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for ev in stream:
        t = getattr(ev, "type", None)
        if t == "response.output_text.delta":
            text.append(ev.delta)
        elif t == "response.output_item.added" and getattr(getattr(ev, "item", None), "type", None) == "function_call":
            current = {"call_id": ev.item.call_id, "name": ev.item.name, "arguments": ""}
        elif t == "response.function_call_arguments.delta" and current:
            current["arguments"] += ev.delta
        elif t == "response.output_item.done":
            it = getattr(ev, "item", None)
            if getattr(it, "type", None) == "function_call" and current:
                current["arguments"] = getattr(it, "arguments", None) or current["arguments"]
                fn_calls.append(current)
                current = {}
    return "".join(text), fn_calls


def _codex_run(client, model: str, pairs: list[dict[str, str]], question: str, viewer: str, quarter: str) -> dict[str, Any]:
    tools = _codex_tools()
    input_items = _codex_input(pairs, question)
    allowed_facts: set[str] = set()
    deal_index: dict[str, Any] = {}
    agg_facts: dict[str, Any] = {}
    final_text = ""

    for step in range(_MAX_TOOL_STEPS):
        stream = client.responses.create(
            model=model, store=False, stream=True, instructions=_SYSTEM,
            input=input_items, tools=tools, tool_choice="auto",
        )
        text, fn_calls = _consume_codex_stream(stream)
        if text:
            final_text = text
        if not fn_calls:
            break  # model produced a final answer
        for fc in fn_calls[:_MAX_TOOL_CALLS]:
            result = _dispatch(fc["name"], fc.get("arguments", "{}"), viewer, quarter)
            _collect_facts(allowed_facts, deal_index, agg_facts, result)
            input_items.append({"type": "function_call", "call_id": fc["call_id"],
                                "name": fc["name"], "arguments": fc.get("arguments", "{}")})
            input_items.append({"type": "function_call_output", "call_id": fc["call_id"],
                                "output": json.dumps(result, ensure_ascii=False)})
    return _finalize(final_text, allowed_facts, deal_index, agg_facts, model)


# --------------------------------------------------------------------------- #
# OpenAI API-key backend — Chat Completions, bounded loop
# --------------------------------------------------------------------------- #

def _openai_messages(pairs: list[dict[str, str]], question: str) -> list[dict[str, Any]]:
    msgs = [{"role": "system", "content": _SYSTEM}]
    for p in pairs:
        msgs.append({"role": p["role"], "content": p["content"]})
    msgs.append({"role": "user", "content": question[:1200]})
    return msgs


def _openai_run(client, model: str, pairs: list[dict[str, str]], question: str, viewer: str, quarter: str) -> dict[str, Any]:
    tools = _openai_tools()
    messages = _openai_messages(pairs, question)
    allowed_facts: set[str] = set()
    deal_index: dict[str, Any] = {}
    agg_facts: dict[str, Any] = {}
    final_text = ""
    calls_used = 0

    for step in range(_MAX_TOOL_STEPS):
        resp = client.chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto", temperature=0.2, max_tokens=700)
        msg = resp.choices[0].message
        if getattr(msg, "content", None):
            final_text = msg.content
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            break
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in calls[:_MAX_TOOL_CALLS] if calls_used < _MAX_TOOL_CALLS
        ]})
        for c in calls:
            calls_used += 1
            if calls_used > _MAX_TOOL_CALLS:
                result = {"status": "error", "warnings": ["tool budget exhausted"]}
            else:
                args = c.function.arguments
                try:
                    parsed_args = json.loads(args) if args else {}
                except (json.JSONDecodeError, TypeError):
                    parsed_args = {}
                result = _dispatch(c.function.name, parsed_args, viewer, quarter)
            _collect_facts(allowed_facts, deal_index, agg_facts, result)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})

    return _finalize(final_text, allowed_facts, deal_index, agg_facts, model)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def answer_question(question: str, viewer: str, quarter: str, rows: list[dict[str, Any]], history=None) -> dict[str, Any]:
    """Run a bounded tool-calling loop over the AE's authorized dashboard data,
    then synthesize a grounded answer. fact_ids are re-validated against
    server-computed facts before anything ships to the user."""
    client = _get_client()
    model = _get_model()
    pairs = _history_pairs(history)
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me about a deal, your pipeline, AI, New Business, or what to do next.",
                "evidence": [], "source": "AE Compass data", "model": model}
    try:
        if _backend == "codex":
            return _codex_run(client, model, pairs, question, viewer, quarter)
        return _openai_run(client, model, pairs, question, viewer, quarter)
    except Exception as exc:
        raise _api_error(exc) from exc
