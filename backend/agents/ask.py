"""Ask Kaagaz: one question about the 5 schemes or this family's check, answered by an agent on Muse Spark Open (task
"ask"), with every answer fact-checked before it is shown.

A small LangGraph graph:
    think -> tools -> think ... (at most ASK_MAX_TOOL_CALLS lookups; read-only tools, agents/ask_tools.py)
    think -> check (the model called `reply`) -> done | think (one retry, told what failed) | not_sure
    think -> unavailable (the 20 s deadline passed, or the provider failed)
- check (agents/ask_check.py) is deterministic: numbers, schemes, offices, fees, eligibility, language, length.
- Refusals (out of scope, ID numbers, other languages), "I'm not sure" with the relevant line of the check, and
  "check at the office" notes come from data/templates/ask; sources and chips come from the tool results.
The model writes only the answer text. Nothing about the question or the family is logged: token counts only.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict
from urllib.parse import urlparse

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from openai import APIError
from pydantic import BaseModel

from agents.ask_check import Evidence, _schemes_in, check
from agents.ask_tools import REPLY_TOOL, AskToolBox, Chip, FamilyContext, load_ask, member_name, scheme_short
from agents.catalog import scheme_card
from agents.reasons import load_reasons
from agents.speech import SCRIPTS, say_in_script
from agents.voice import load_voice
from app.config import get_settings
from clients.llm import ChatResponse, EmptyResponse, LLMError, TokenUsage, chat
from rules.loader import load_schemes
from schemas.languages import ENGLISH_NAMES
from vision.text import redact_identity_numbers

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "ask.md").read_text(encoding="utf-8")
LANGUAGE_NAMES = ENGLISH_NAMES
LAKH = {"en": "lakh", "hi": "लाख", "mr": "लाख", "ta": "லட்சம்", "te": "లక్షల", "kn": "ಲಕ್ಷ"}
RUPEES = {"en": "rupees", "hi": "रुपये", "mr": "रुपये", "ta": "ரூபாய்", "te": "రూపాయలు", "kn": "ರೂಪಾಯಿ"}
MAX_TURNS = 8
FIXED_KINDS = ("out_of_scope", "id_number", "other_language")
Kind = Literal["answer", "out_of_scope", "id_number", "other_language", "not_sure", "unavailable"]
Chat = Callable[..., ChatResponse]

# What a rule is about, to tell whether an answer states it (for sources and "check at the office").
TOPICS = {
    "gender": r"wom[ae]n|female|महिला|स्त्री",
    "age": r"\bage\b|\byears?\b|वय|उम्र|आयु|वर्ष",
    "income": r"income|उत्पन्न|\bआय\b|₹",
    "caste": r"caste|जात|जाति|\bSC\b|\bST\b",
    "documents": r"document|card|certificate|दस्तावेज़|दस्तावेज|कागदपत्र|कार्ड|दाखला|प्रमाण",
    "benefit": r"benefit|month|pension|grant|connection|लाभ|फायदा|महिना|दरमहा|माह|पेंशन|निवृत्तीवेतन|अनुदान|कनेक्शन|जोडणी",
}
CHECK_TOPIC = {"gender": "gender", "age_min": "age", "age_max": "age", "age_below": "age", "income_max": "income",
               "income_bands": "income", "income_certificate_unless_card": "documents", "caste_household": "caste",
               "caste_applicant": "caste", "documents": "documents"}


class Source(BaseModel):
    label: str
    url: str


class AskAnswer(BaseModel):
    kind: Kind
    text: str
    note: str | None = None  # "check it at the office", when the answer states something unverified
    sources: list[Source] = []
    chips: list[Chip] = []
    attempts: int = 0  # replies checked
    tool_calls: int = 0
    failures: list[str] = []  # why the first reply (and, for not_sure, the second) was rejected; never shown
    usage: TokenUsage = TokenUsage()
    seconds: float = 0.0
    trace: list[dict[str, Any]] = []  # tool calls and replies, for evals


class AskState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    status: str  # think | tools | check | done | not_sure | unavailable
    pending: list[dict[str, Any]]  # data tool calls to run
    reply: dict[str, Any] | None
    reply_call: str | None  # tool call id of the reply
    skipped: list[str]  # tool call ids made alongside a reply (not run)
    tool_calls: int
    turns: int
    attempts: int
    failures: list[str]
    usage: dict[str, int]
    trace: list[dict[str, Any]]


# ---------- nodes ----------

def _rt(config: RunnableConfig) -> dict[str, Any]:
    return config["configurable"]


def think(state: AskState, config: RunnableConfig) -> AskState:
    rt = _rt(config)
    remaining = rt["deadline"] - time.monotonic()
    turns = state.get("turns", 0) + 1
    if remaining < 0.5 or turns > MAX_TURNS:
        return {"status": "not_sure" if state.get("failures") else "unavailable", "turns": turns}
    toolbox: AskToolBox = rt["toolbox"]
    tools = [*toolbox.schemas, REPLY_TOOL] if state.get("tool_calls", 0) < rt["max_tool_calls"] else [REPLY_TOOL]
    try:
        resp = rt["llm"](state["messages"], task="ask", tools=tools, timeout=remaining, tool_choice="required")
    except EmptyResponse:
        return {"turns": turns, "status": "think",
                "messages": [*state["messages"], {"role": "user", "content": "Call reply with your answer."}]}
    except (LLMError, APIError, ValueError) as e:  # ValueError: the provider is not configured
        logger.warning("ask: model call failed: %s", type(e).__name__)
        # after a rejected reply there is no second chance: "not sure" with the check's own line
        return {"status": "not_sure" if state.get("failures") else "unavailable", "turns": turns}
    usage = dict(state.get("usage") or {})
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + resp.usage.prompt_tokens
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + resp.usage.completion_tokens
    trace = [*state.get("trace", []), {"turn": turns, "content": resp.content,
                                       "calls": [{"tool": c.name, "args": c.arguments} for c in resp.tool_calls]}]
    messages = list(state["messages"])
    out: AskState = {"turns": turns, "usage": usage, "trace": trace}
    if not resp.tool_calls:
        # A tool call is required on every turn: text alone is the model thinking aloud (Muse Spark Open sometimes
        # leaks its reasoning as content), never an answer to show.
        messages.append({"role": "user", "content": "Call a tool: look something up, or call reply with your answer."})
        return {**out, "messages": messages, "status": "think"}
    messages.append({"role": "assistant", "content": resp.content or "", "tool_calls": [
        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in resp.tool_calls]})
    reply = next((c for c in resp.tool_calls if c.name == "reply"), None)
    if reply is None:
        return {**out, "messages": messages, "status": "tools",
                "pending": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in resp.tool_calls]}
    try:
        args = json.loads(reply.arguments or "{}")
        parsed = {"kind": args.get("kind", "answer"), "text": str(args.get("text") or ""),
                  "chips": [str(c) for c in args.get("chips") or []]}
    except (json.JSONDecodeError, AttributeError):
        parsed = {"kind": "answer", "text": "", "chips": [], "invalid": True}
    return {**out, "messages": messages, "status": "check", "reply": parsed, "reply_call": reply.id,
            "skipped": [c.id for c in resp.tool_calls if c.id != reply.id]}


def tools(state: AskState, config: RunnableConfig) -> AskState:
    rt = _rt(config)
    toolbox: AskToolBox = rt["toolbox"]
    messages, count = list(state["messages"]), state.get("tool_calls", 0)
    for c in state.get("pending", []):
        if count >= rt["max_tool_calls"]:
            result: dict[str, Any] = {"error": "No more lookups for this question: answer now with reply."}
        else:
            result = toolbox.call(c["name"], c["arguments"])
            count += 1
        messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, ensure_ascii=False)})
    return {"messages": messages, "tool_calls": count, "pending": [], "status": "think"}


def evidence(toolbox: AskToolBox, language: str = "en") -> Evidence:
    ctx = toolbox.ctx
    ev = Evidence(used=toolbox.used)
    if ctx is None:
        return ev
    for m in ctx.data.members:
        names = [n for n in (m.name_en, m.name_mr) if n]
        if language in SCRIPTS and m.name_mr:  # how a model may write the name in Tamil, Telugu or Kannada
            names.append(say_in_script(m.name_mr, language))
        ev.members[m.member_id] = [*names, *(n.split()[0] for n in names if n.split())]
    looked_up = {u["result"].get("member_id") for u in toolbox.used if u["tool"] == "get_member_results"}
    for o in ctx.data.outcomes:
        if o.member_id in looked_up:
            ev.outcomes[(o.member_id, o.scheme_id)] = o.outcome
    return ev


def check_reply(state: AskState, config: RunnableConfig) -> AskState:
    rt = _rt(config)
    reply = state["reply"] or {}
    attempts = state.get("attempts", 0) + 1
    if reply.get("kind") == "other_language" and rt.get("indic_question"):
        # written in Devanagari, Tamil, Telugu or Kannada: one of the six languages, so it is answered
        failures = ["Wrong kind: the question is written in Hindi, Marathi, Tamil, Telugu or Kannada, which Kaagaz "
                    "answers. Do not use kind other_language: look up what is needed and reply with kind answer, in "
                    f"{LANGUAGE_NAMES[rt['language']]}."]
    elif reply.get("kind") in FIXED_KINDS:
        return {"status": "done", "attempts": attempts}
    else:
        failures = (["reply arguments were not valid JSON"] if reply.get("invalid")
                        else check(reply.get("text", ""), rt["language"], evidence(rt["toolbox"], rt["language"])))
    if not failures:
        return {"status": "done", "attempts": attempts}
    all_failures = [*state.get("failures", []), *failures]
    if attempts >= 2:
        return {"status": "not_sure", "attempts": attempts, "failures": all_failures}
    messages = list(state["messages"])
    feedback = {"rejected": failures, "instruction": "Fix these problems (look things up if needed) and call reply again."}
    for skipped in state.get("skipped", []):
        messages.append({"role": "tool", "tool_call_id": skipped, "content": json.dumps({"skipped": "a reply was given"})})
    messages.append({"role": "tool", "tool_call_id": state["reply_call"], "content": json.dumps(feedback, ensure_ascii=False)})
    return {"status": "think", "attempts": attempts, "failures": all_failures, "messages": messages}


def _route(state: AskState) -> str:
    return state["status"] if state["status"] in ("think", "tools", "check") else END


def build_ask_graph() -> Any:
    g = StateGraph(AskState)
    g.add_node("think", think)
    g.add_node("tools", tools)
    g.add_node("check", check_reply)
    g.set_entry_point("think")
    g.add_conditional_edges("think", _route, {"tools": "tools", "check": "check", "think": "think", END: END})
    g.add_edge("tools", "think")
    g.add_conditional_edges("check", _route, {"think": "think", END: END})
    return g.compile()


_GRAPH = None


def graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_ask_graph()
    return _GRAPH


# ---------- sources, notes and fallbacks (deterministic) ----------

def _label(url: str) -> str:
    host = urlparse(url).netloc
    return host.removeprefix("www.") or url


def sources_and_note(text: str, toolbox: AskToolBox, language: str) -> tuple[list[Source], str | None]:
    """Source links for the rules and office facts the answer states, and "check it at the office" if any of them
    (or the scheme benefit it mentions) is not verified."""
    urls: list[str] = []
    unverified = False
    named = set(_schemes_in(text))
    lookups = [u["result"] for u in toolbox.used if u["tool"] == "get_scheme_rules" and "scheme_id" in u["result"]]
    topics = {k for k, rx in TOPICS.items() if re.search(rx, text, re.IGNORECASE)}
    for r in lookups:
        if r["scheme_id"] not in named and len(lookups) > 1:
            continue
        for rule in r["rules"]:
            check_topic = CHECK_TOPIC.get(next((x.check for s in load_schemes() if s.id == r["scheme_id"]
                                                for x in s.rules if x.id == rule["rule_id"]), ""), "")
            if check_topic in topics:
                urls += rule["source_urls"]
                unverified |= not rule["verified"]
        if "benefit" in topics:
            urls += r["benefit"]["source_urls"]
            unverified |= not r["benefit"]["verified"]
    from agents.ask_check import office_tags

    tags = office_tags(text)
    for u in toolbox.used:
        if u["tool"] == "get_office_facts":
            for p in u["result"].get("procedures", []):
                office = p.get("office") or {}
                named = office_tags(office.get("value", "")) if office else set()
                if named and named <= tags:  # every part of the office's name is in the answer
                    urls += [x for x in (p.get("source_url"), office.get("source_url")) if x]
                    unverified |= not office.get("verified", True) or not p.get("verified", True)
        elif u["tool"] == "get_plan":
            for s in u["result"].get("steps", []):
                for f in [s.get("office"), s.get("fee"), s.get("time_limit"), *(s.get("bring") or [])]:
                    if f and not f.get("verified") and f.get("text") and f["text"].casefold() in text.casefold():
                        unverified = True
    sources = [Source(label=_label(u), url=u) for u in dict.fromkeys(urls)]
    return sources, load_ask(language).replies["check_at_office"] if unverified else None


def _mentioned_members(question: str, ctx: FamilyContext) -> list[str]:
    low = question.casefold()
    out = []
    for m in ctx.data.members:
        names = [n for n in (m.name_en, m.name_mr) if n]
        if any(w.casefold() in low for n in names for w in n.split()[:1]):
            out.append(m.member_id)
    return out


def _mentioned_documents(question: str) -> set[str]:
    low = question.casefold()
    return {t for language in LANGUAGE_NAMES for t, name in load_voice(language).documents.items()
            if name.casefold() in low}


def relevant_line(question: str, ctx: FamilyContext | None, language: str) -> str | None:
    """The line of the check (or of the scheme rules, before a check) that the question is most likely about."""
    t = load_ask(language)
    schemes = _schemes_in(question)
    if ctx is None:
        if not schemes:
            return None
        card = scheme_card(next(s for s in load_schemes() if s.id == schemes[0]), language)
        return t.lines["scheme"].format(scheme=card.name, text=" ".join([card.benefit.text, *(r.text for r in card.rules[:3])]))
    members = _mentioned_members(question, ctx)
    outcomes = [o for o in ctx.data.outcomes if (not members or o.member_id in members)
                and (not schemes or o.scheme_id in schemes)]
    if (members or schemes) and outcomes and (schemes or not any(p.member_id in members for p in ctx.data.problems)):
        o = outcomes[0]
        reason = (o.reasons or o.warnings or [""])[0]
        return t.lines["outcome"].format(member=member_name(ctx, o.member_id, language) or "",
                                         scheme=scheme_short(o.scheme_id, language), reason=reason)
    doc_types = _mentioned_documents(question)
    problems = ([p for p in ctx.data.problems if (not members or p.member_id in members)
                 and (not doc_types or set(p.document_types) & doc_types)]
                or [p for p in ctx.data.problems if not members or p.member_id in members] or ctx.data.problems)
    if problems:
        p = problems[0]
        issues = load_reasons(language).issues
        return t.lines["problem"].format(member=member_name(ctx, p.member_id, language) or "",
                                         reason=issues.get(p.type, p.type)).removeprefix(": ")
    if ctx.data.steps:
        return t.lines["step"].format(text=ctx.data.steps[0].voice)
    return None


# ---------- speech ----------

def _big(n: int, language: str) -> str:
    """Numbers up to 99,99,999 the Indian way (2 lakh 50 thousand); speech_text spells out up to 9999 only."""
    from agents.speech import number_words

    w = load_voice(language).numbers
    lakh, rest = divmod(n, 100000)
    thousands, rest = divmod(rest, 1000)
    parts = [f"{number_words(lakh, language)} {LAKH[language]}"] if lakh else []
    if thousands:
        parts.append(f"{w.words[thousands]} {w.thousand}")
    if rest:
        parts.append(number_words(rest, language))
    return " ".join(parts)


def answer_speech(text: str, language: str) -> str:
    """TTS input for an answer: ₹ amounts and large numbers in words, then agents.speech.speech_text."""
    from agents.speech import speech_text

    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # ₹2,50,000 -> ₹250000
    text = re.sub(r"(?:₹|\bRs\.?)\s*(\d+)", lambda m: f"{m.group(1)} {RUPEES[language]}", text)
    text = re.sub(r"\b\d{5,7}\b", lambda m: _big(int(m.group()), language), text)
    return speech_text(text, language)


# ---------- entry point ----------

# Letters of the six languages' scripts (Latin, Devanagari, Tamil, Telugu, Kannada); any other letter is another language
OWN_LETTERS = re.compile(r"[A-Za-zऀ-ॿ஀-௿ఀ-౿ಀ-೿]")
OTHER_LETTERS = re.compile(r"[^\W\d_A-Za-zऀ-ॿ஀-௿ఀ-౿ಀ-೿]")


def indic_script(question: str) -> bool:
    """Mostly Devanagari, Tamil, Telugu or Kannada letters: certainly one of the six languages."""
    indic = len(re.findall(r"[ऀ-ॿ஀-௿ఀ-౿ಀ-೿]", question))
    return indic > len(re.findall(r"[A-Za-z]", question)) and not other_script(question)


def other_script(question: str) -> bool:
    """Mostly written in another script (Bengali, Gujarati, Gurmukhi, Odia, Malayalam, Urdu ...)."""
    own, other = len(OWN_LETTERS.findall(question)), len(OTHER_LETTERS.findall(question))
    return other > own

def ask(question: str, language: str, ctx: FamilyContext | None = None, *, llm: Chat = chat,
        timeout_s: float | None = None, max_tool_calls: int | None = None) -> AskAnswer:
    if other_script(question):  # written in a script none of the six languages use: the fixed reply, no model call
        return AskAnswer(kind="other_language", text=load_ask(language).replies["other_language"])
    settings = get_settings()
    timeout_s = settings.ask_timeout_s if timeout_s is None else timeout_s
    max_tool_calls = settings.ask_max_tool_calls if max_tool_calls is None else max_tool_calls
    start = time.monotonic()
    toolbox = AskToolBox(language, ctx)
    check_line = ("A check of this family is attached: use the family tools." if ctx is not None
                  else "No check is attached yet: answer only about the 5 schemes; for questions about the family's "
                       "own documents, say to run a check first.")
    system = (PROMPT.replace("{language_name}", LANGUAGE_NAMES[language]).replace("{check_line}", check_line)
              .replace("{brand}", load_ask(language).brand))
    state: AskState = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
                       "status": "think", "tool_calls": 0, "attempts": 0, "turns": 0, "usage": {}, "trace": []}
    config = {"configurable": {"toolbox": toolbox, "llm": llm, "deadline": start + timeout_s, "language": language,
                               "indic_question": indic_script(question),
                               "max_tool_calls": max_tool_calls}, "recursion_limit": 40}
    final: AskState = graph().invoke(state, config)
    t = load_ask(language)
    status, reply = final.get("status"), final.get("reply") or {}
    usage = TokenUsage(prompt_tokens=final.get("usage", {}).get("prompt_tokens", 0),
                       completion_tokens=final.get("usage", {}).get("completion_tokens", 0))
    usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
    common = {"attempts": final.get("attempts", 0), "tool_calls": final.get("tool_calls", 0),
              "failures": final.get("failures", []), "usage": usage, "trace": final.get("trace", [])}
    if status == "done" and reply.get("kind") in FIXED_KINDS:
        answer = AskAnswer(kind=reply["kind"], text=t.replies[reply["kind"]], **common)
    elif status == "done":
        text = redact_identity_numbers(reply["text"].strip())
        sources, note = sources_and_note(text, toolbox, language)
        chips = [toolbox.chips[c] for c in dict.fromkeys(reply.get("chips", [])) if c in toolbox.chips]
        answer = AskAnswer(kind="answer", text=text, note=note, sources=sources, chips=chips, **common)
    elif status == "not_sure":
        line = relevant_line(question, ctx, language)
        lead = t.replies["not_sure" if ctx is not None else "not_sure_no_check"]
        answer = AskAnswer(kind="not_sure", text=f"{lead} {line}" if line else t.replies["not_sure_nothing"], **common)
    else:
        answer = AskAnswer(kind="unavailable", text=t.replies["unavailable"], **common)
    answer.seconds = round(time.monotonic() - start, 2)
    logger.info("ask: %s, %d replies checked, %d lookups, %d prompt + %d completion tokens, %.1f s", answer.kind,
                answer.attempts, answer.tool_calls, usage.prompt_tokens, usage.completion_tokens, answer.seconds)
    return answer
