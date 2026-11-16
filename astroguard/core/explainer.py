# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Explains alerts with retrieval-augmented generation (RAG).

1. Retrieve the top passages from the knowledge base (BM25).
2. If Claude is available (the `anthropic` package is installed and credentials are set),
   ask Claude for a short, grounded explanation that cites the passages.
3. Otherwise build a template explanation from the retrieved passages. The system works
   fully offline.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .knowledge import Retriever

MODEL = os.environ.get("HMS_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = (
    "You are the explanation component of an astronaut health-monitoring system. You receive one alert "
    "produced by a multi-agent correlation engine, plus reference passages from a knowledge base that "
    "summarizes NASA human-spaceflight health guidance. Write 3-5 plain sentences for the crew and flight "
    "surgeon: what is happening, why it is a health or mission risk, and why the recommended actions help. "
    "Base every claim on the passages and cite them inline as [id]. If the passages do not support a "
    "claim, leave it out. No headings, no bullet lists, no preamble."
)


class Explainer:
    def __init__(self, store):
        self.store = store
        self.retriever = Retriever()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="explainer")
        self.client = None
        self.mode = "retrieval-only"
        self.llm_calls = 0
        self.llm_errors = 0
        self.last_error: str | None = None
        self._lock = threading.Lock()
        if os.environ.get("HMS_DISABLE_LLM") != "1":
            try:
                import anthropic  # optional dependency

                if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("HMS_LLM") == "1":
                    self.client = anthropic.Anthropic()
                    self.mode = f"claude ({MODEL})"
            except ImportError:
                pass

    def explain(self, alert: dict, query: str):
        self.pool.submit(self._explain, alert, query)

    def _explain(self, alert, query):
        docs = self.retriever.search(query + " " + alert["title"], k=3)
        citations = [{"id": d["id"], "title": d["title"], "source": d["source"], "score": d["score"]} for d in docs]
        text, by = None, "retrieval"
        if self.client is not None:
            t0 = time.time()
            try:
                text = self._ask_claude(alert, docs)
                by = f"claude ({MODEL}, {time.time() - t0:.1f}s)"
            except Exception as e:  # noqa: BLE001 - fall back to retrieval on any API failure
                with self._lock:
                    self.llm_errors += 1
                    self.last_error = repr(e)[:200]
                self.store.log("warn", "explainer", f"Claude call failed, using retrieval fallback: {e!r}"[:200])
        if not text:
            text = self._template(alert, docs)
        with self.store.lock:
            alert["explanation"] = text
            alert["citations"] = citations
            alert["explained_by"] = by

    def _ask_claude(self, alert, docs) -> str | None:
        passages = "\n\n".join(f"[{d['id']}] {d['title']} (source: {d['source']})\n{d['text']}" for d in docs)
        evidence = "\n".join(f"- {e['agent']}: {e['message']}" for e in alert["evidence"])
        user = (
            f"ALERT ({alert['severity']}): {alert['title']}\n"
            f"Root cause (from correlation engine): {alert['root_cause']}\n"
            f"Crew affected: {', '.join(alert['crew']) or 'cabin-wide'}\n"
            f"Evidence from agents:\n{evidence}\n"
            f"Recommended actions: {'; '.join(alert['actions'])}\n\n"
            f"REFERENCE PASSAGES:\n{passages}"
        )
        with self._lock:
            self.llm_calls += 1
        response = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines on a policy check, the API retries on a fallback model
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            return None
        return "".join(b.text for b in response.content if b.type == "text").strip() or None

    @staticmethod
    def _template(alert, docs) -> str:
        if not docs:
            return alert["root_cause"] + "."
        lead = docs[0]
        first = lead["text"].split(". ")
        why = ". ".join(first[:2]).rstrip(".")
        parts = [f"{alert['root_cause']}.", f"{why} [{lead['id']}]."]
        if len(docs) > 1:
            parts.append(f"Related guidance: {docs[1]['title']} [{docs[1]['id']}].")
        return " ".join(parts)

    def status(self):
        return {"mode": self.mode, "llm_calls": self.llm_calls, "llm_errors": self.llm_errors,
                "last_error": self.last_error, "kb_passages": len(self.retriever.docs)}
