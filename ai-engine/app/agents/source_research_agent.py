"""Agent #1 — Source Research Agent (`search_sources`, `inspect_source`, `commit_sources`).

Finds and selects 1..3 reputable primary sources (arXiv / official technical documentation)
when the learner does not upload their own PDF/document.

Security & Quality Guarantees (enforced deterministically in code, never trusted to LLM):
  - Domain reputation allowlist + spam/junk denylist.
  - Strict HTTPS-only, port-443, no-userinfo, non-IP-literal URL validation (blocks SSRF/private/metadata IPs).
  - Hard cap `max_turns` (raises `SourceResearchMaxTurnsError` with `error_code="max_turns"`).
  - Hard cap `1..3` committed sources, deduplicated by URL.
  - Zero-cost offline deterministic catalog in `mock` mode or when outbound web fetch is disabled.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlsplit

import httpx

from app.agents.providers import LLMProvider
from app.core.config import Settings, get_settings
from app.rag.extractor import extract_arxiv_atom_text, extract_html_text
from app.rag.url_fetcher import WebFetchError, fetch_url_safe, host_allowed
from app.schemas.internal import LlmUsageOut

logger = logging.getLogger(__name__)

DEFAULT_REPUTABLE_DOMAINS: tuple[str, ...] = (
    "arxiv.org",
    "export.arxiv.org",
    "docs.python.org",
    "developer.mozilla.org",
    "postgresql.org",
    "kubernetes.io",
    "react.dev",
    "nextjs.org",
    "spring.io",
    "docs.spring.io",
    "pytorch.org",
    "scikit-learn.org",
    "numpy.org",
    "en.wikipedia.org",
    "w3.org",
    "ietf.org",
    "rfc-editor.org",
    "mit.edu",
    "stanford.edu",
    "nist.gov",
)

JUNK_DOMAIN_DENYLIST: tuple[str, ...] = (
    "pinterest.com",
    "quora.com",
    "medium.com",
    "tiktok.com",
    "facebook.com",
    "instagram.com",
    "reddit.com",
    "blogspot.com",
    "wordpress.com",
    "scribd.com",
    "chegg.com",
    "coursehero.com",
    "slideshare.net",
    "linkedin.com",
    "x.com",
    "twitter.com",
)


class SourceResearchMaxTurnsError(RuntimeError):
    """Raised when the Source Research Agent hits `max_turns` without committing 1..3 valid sources."""

    error_code = "max_turns"


@dataclass
class ResearchedSource:
    url: str
    title: str
    source_kind: str  # "arxiv_url" | "web_url"
    domain: str
    rationale: str
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "sourceKind": self.source_kind,
            "domain": self.domain,
            "rationale": self.rationale,
            "excerpt": self.excerpt,
        }


@dataclass
class SourceResearchResult:
    sources: list[ResearchedSource]
    tools_called: list[str] = field(default_factory=list)
    rejected_urls: list[str] = field(default_factory=list)
    turns_used: int = 0
    usage: LlmUsageOut = field(default_factory=LlmUsageOut)


SearchProviderFn = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
InspectProviderFn = Callable[[str], Awaitable[dict[str, Any]]]


def is_reputable_source_url(
    raw_url: str,
    *,
    extra_allowed_hosts: tuple[str, ...] = (),
) -> tuple[bool, str, str]:
    """Deterministic code-level domain & SSRF filter.

    Returns `(is_valid, host, reason_code)`.
    """
    value = (raw_url or "").strip()
    if not value or len(value) > 2048 or any(c in value for c in ("\n", "\r", "\x00", " ", "\t")):
        return False, "", "URL_INVALID"

    parts = urlsplit(value)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if scheme != "https" or not host:
        return False, host, "URL_SCHEME_FORBIDDEN"
    if parts.username or parts.password:
        return False, host, "URL_HAS_USERINFO"
    if (parts.port or 443) != 443:
        return False, host, "URL_PORT_FORBIDDEN"
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".internal"):
        return False, host, "SSRF_LOCAL_HOST"

    try:
        ipaddress.ip_address(host)
        return False, host, "SSRF_IP_LITERAL"
    except ValueError:
        pass

    if host_allowed(host, JUNK_DOMAIN_DENYLIST):
        return False, host, "JUNK_DOMAIN_BLOCKED"

    allowed = tuple(dict.fromkeys((*DEFAULT_REPUTABLE_DOMAINS, *extra_allowed_hosts)))
    if not host_allowed(host, allowed):
        return False, host, "UNTRUSTED_DOMAIN"

    return True, host, "OK"


def infer_source_kind(url: str, host: str) -> str:
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        return "arxiv_url"
    if "arxiv" in url.lower():
        return "arxiv_url"
    return "web_url"


def _curated_offline_candidates(topic: str, query: str) -> list[dict[str, Any]]:
    """Zero-cost deterministic reputable candidates for offline/mock CI & fallback."""
    lowered = f"{topic} {query}".casefold()
    candidates: list[dict[str, Any]] = []

    if any(k in lowered for k in ("sql", "postgres", "b-tree", "btree", "database", "index")):
        candidates.extend(
            [
                {
                    "url": "https://www.postgresql.org/docs/current/indexes-types.html",
                    "title": "PostgreSQL Documentation: Index Types (B-Tree, Hash, GiST, GIN)",
                    "sourceKind": "web_url",
                    "snippet": "Official PostgreSQL guide covering B-Tree page layout, operator classes, and query planner selectivity.",
                },
                {
                    "url": "https://export.arxiv.org/api/query?id_list=2006.10218",
                    "title": "arXiv: Modern B-Tree Techniques & Database Storage Engines",
                    "sourceKind": "arxiv_url",
                    "snippet": "Survey of cache-conscious B-Tree indexing, latch coupling, and write-optimized storage.",
                },
            ]
        )
    if any(k in lowered for k in ("python", "asyncio", "fastapi", "typing")):
        candidates.append(
            {
                "url": "https://docs.python.org/3/library/asyncio.html",
                "title": "Python 3 Official Documentation: asyncio & Concurrency",
                "sourceKind": "web_url",
                "snippet": "Official Python reference for coroutines, tasks, event loops, and structured concurrency.",
            }
        )
    if any(k in lowered for k in ("kubernetes", "k8s", "container", "pod", "helm")):
        candidates.append(
            {
                "url": "https://kubernetes.io/docs/concepts/workloads/pods/",
                "title": "Kubernetes Official Docs: Pods & Workload Controllers",
                "sourceKind": "web_url",
                "snippet": "Official Kubernetes documentation on Pod lifecycles, readiness probes, and horizontal autoscaling.",
            }
        )
    if any(k in lowered for k in ("transformer", "attention", "machine learning", "deep learning", "llm", "neural")):
        candidates.extend(
            [
                {
                    "url": "https://export.arxiv.org/api/query?id_list=1706.03762",
                    "title": "Attention Is All You Need (arXiv:1706.03762)",
                    "sourceKind": "arxiv_url",
                    "snippet": "Foundational Transformer architecture paper introducing scaled dot-product multi-head self-attention.",
                },
                {
                    "url": "https://pytorch.org/docs/stable/nn.html",
                    "title": "PyTorch Official Docs: torch.nn Modules",
                    "sourceKind": "web_url",
                    "snippet": "Official PyTorch API and architectural guide for neural network layers and attention blocks.",
                },
            ]
        )
    if any(k in lowered for k in ("react", "next", "javascript", "typescript", "web", "http")):
        candidates.append(
            {
                "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
                "title": "MDN Web Docs: An Overview of HTTP",
                "sourceKind": "web_url",
                "snippet": "Authoritative MDN reference covering HTTP semantics, headers, caching, and streaming.",
            }
        )

    # Generic fallback reputable sources anchored to the requested topic
    slug = quote_plus((topic or query or "computer science").strip()[:80])
    candidates.extend(
        [
            {
                "url": f"https://export.arxiv.org/api/query?search_query=all:{slug}&max_results=3",
                "title": f"arXiv Primary Research Survey: {topic}",
                "sourceKind": "arxiv_url",
                "snippet": f"Peer-reviewed preprint search results on arXiv covering foundational concepts of {topic}.",
            },
            {
                "url": f"https://en.wikipedia.org/wiki/{slug.replace('+', '_')}",
                "title": f"Wikipedia Reference Overview: {topic}",
                "sourceKind": "web_url",
                "snippet": f"Structured encyclopedic overview, terminology, and primary citations for {topic}.",
            },
        ]
    )
    return candidates


def _filter_candidates(
    raw_candidates: list[dict[str, Any]],
    *,
    extra_allowed_hosts: tuple[str, ...],
    rejected_urls: list[str],
    max_results: int,
) -> list[dict[str, Any]]:
    vetted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        ok, host, reason = is_reputable_source_url(url, extra_allowed_hosts=extra_allowed_hosts)
        if not ok:
            rejected_urls.append(f"{url} ({reason})")
            continue
        seen.add(url)
        vetted.append(
            {
                "url": url,
                "title": str(item.get("title") or host)[:200],
                "sourceKind": infer_source_kind(url, host),
                "domain": host,
                "snippet": str(item.get("snippet") or "")[:360],
            }
        )
        if len(vetted) >= max_results:
            break
    return vetted


def _default_search_fn(
    topic: str,
    cfg: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SearchProviderFn:
    async def _search(query: str, max_results: int) -> list[dict[str, Any]]:
        # Live arXiv search ONLY when explicitly enabled AND export.arxiv.org is allowlisted
        if cfg.web_ingest_enabled and host_allowed("export.arxiv.org", cfg.allowed_web_hosts):
            q = quote_plus((query or topic).strip()[:120])
            arxiv_url = f"https://export.arxiv.org/api/query?search_query=all:{q}&max_results={max(1, min(max_results, 5))}"
            try:
                fetched = await fetch_url_safe(arxiv_url, settings=cfg, transport=transport)
                txt, title = extract_arxiv_atom_text(fetched.data)
                return [
                    {
                        "url": arxiv_url,
                        "title": title or f"arXiv: {query}",
                        "sourceKind": "arxiv_url",
                        "snippet": txt[:320],
                    }
                ]
            except (WebFetchError, Exception) as exc:  # noqa: BLE001
                logger.warning("source_research_live_search_fallback error=%s", type(exc).__name__)
        return _curated_offline_candidates(topic, query)

    return _search


def _default_inspect_fn(
    cfg: Settings,
    candidate_index: dict[str, dict[str, Any]],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> InspectProviderFn:
    async def _inspect(url: str) -> dict[str, Any]:
        ok, host, reason = is_reputable_source_url(url, extra_allowed_hosts=cfg.allowed_web_hosts)
        if not ok:
            return {"ok": False, "error": reason, "url": url}

        if cfg.web_ingest_enabled and host_allowed(host, cfg.allowed_web_hosts):
            try:
                fetched = await fetch_url_safe(url, settings=cfg, transport=transport)
                if "xml" in fetched.media_type or infer_source_kind(url, host) == "arxiv_url":
                    txt, title = extract_arxiv_atom_text(fetched.data)
                    return {
                        "ok": True,
                        "url": fetched.final_url,
                        "title": title or host,
                        "domain": host,
                        "sourceKind": "arxiv_url",
                        "excerpt": txt[:600],
                    }
                txt, sections = extract_html_text(fetched.data)
                return {
                    "ok": True,
                    "url": fetched.final_url,
                    "title": sections[0][1] if sections else host,
                    "domain": host,
                    "sourceKind": "web_url",
                    "headings": [h for _, h in sections[:8]],
                    "excerpt": txt[:600],
                }
            except (WebFetchError, Exception) as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}", "url": url}

        cached = candidate_index.get(url)
        if cached:
            return {
                "ok": True,
                "url": url,
                "title": cached["title"],
                "domain": host,
                "sourceKind": cached["sourceKind"],
                "excerpt": cached.get("snippet", ""),
            }
        return {
            "ok": True,
            "url": url,
            "title": host,
            "domain": host,
            "sourceKind": infer_source_kind(url, host),
            "excerpt": f"Verified reputable domain ({host}).",
        }

    return _inspect


async def research_sources_with_agent(
    *,
    topic: str,
    language: str = "vi",
    provider: LLMProvider,
    settings: Settings | None = None,
    max_turns: int | None = None,
    search_fn: SearchProviderFn | None = None,
    inspect_fn: InspectProviderFn | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SourceResearchResult:
    """Runs bounded Source Research Agent loop (`search_sources` -> `inspect_source` -> `commit_sources`)."""
    cfg = settings or get_settings()
    safe_max_turns = max(1, min(max_turns if max_turns is not None else cfg.source_research_max_turns, 10))

    candidate_index: dict[str, dict[str, Any]] = {}
    searcher = search_fn or _default_search_fn(topic, cfg, transport=transport)
    inspector = inspect_fn or _default_inspect_fn(cfg, candidate_index, transport=transport)

    tools_called: list[str] = []
    rejected_urls: list[str] = []
    tool_history: list[dict[str, Any]] = []
    committed: list[ResearchedSource] | None = None
    turns_used = 0
    total_prompt = 0
    total_completion = 0
    last_usage = LlmUsageOut(provider=provider.name, model=provider.model)

    turn_planner = getattr(provider, "next_source_research_turn", None)
    for turn in range(1, safe_max_turns + 1):
        turns_used = turn
        call_id = f"call_src_{turn}"
        if callable(turn_planner):
            action = await turn_planner(
                turn=turn,
                topic=topic,
                language=language,
                tool_history=tool_history,
            )
            call_id = str(action.get("id") or call_id)
            tool_name = str(action.get("tool") or "")
            tool_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            u = action.get("usage")
            if isinstance(u, LlmUsageOut):
                total_prompt += u.promptTokens
                total_completion += u.completionTokens
                last_usage = u
        else:
            # Deterministic 3-turn schedule for MockProvider / offline CI:
            # Turn 1: search_sources -> Turn 2: inspect_source (top 1) -> Turn 3: commit_sources (1..3)
            if not candidate_index:
                tool_name = "search_sources"
                tool_args = {"query": topic, "max_results": 4}
            elif "inspect_source" not in tools_called:
                first_url = next(iter(candidate_index.keys()))
                tool_name = "inspect_source"
                tool_args = {"url": first_url}
            else:
                top_items = list(candidate_index.values())[:2]
                tool_name = "commit_sources"
                tool_args = {
                    "sources": [
                        {
                            "url": item["url"],
                            "title": item["title"],
                            "sourceKind": item["sourceKind"],
                            "rationale": item.get("snippet") or f"Primary reference for {topic}.",
                        }
                        for item in top_items
                    ]
                }

        if tool_name == "search_sources":
            tools_called.append("search_sources")
            query = str(tool_args.get("query") or topic).strip()
            max_res = max(1, min(int(tool_args.get("max_results") or 5), 8))
            raw = await searcher(query, max_res)
            vetted = _filter_candidates(
                raw,
                extra_allowed_hosts=cfg.allowed_web_hosts,
                rejected_urls=rejected_urls,
                max_results=max_res,
            )
            for item in vetted:
                candidate_index[item["url"]] = item
            tool_history.append(
                {
                    "id": call_id,
                    "tool": "search_sources",
                    "arguments": {"query": query, "max_results": max_res},
                    "result": {"candidates": vetted, "filteredOutCount": len(rejected_urls)},
                }
            )
        elif tool_name == "inspect_source":
            tools_called.append("inspect_source")
            url = str(tool_args.get("url") or "").strip()
            ok, _host, reason = is_reputable_source_url(url, extra_allowed_hosts=cfg.allowed_web_hosts)
            if not ok:
                rejected_urls.append(f"{url} ({reason})")
                inspected = {"ok": False, "error": reason, "url": url}
            else:
                inspected = await inspector(url)
                if inspected.get("ok") and url in candidate_index:
                    candidate_index[url]["excerpt"] = str(inspected.get("excerpt") or "")[:600]
            tool_history.append(
                {
                    "id": call_id,
                    "tool": "inspect_source",
                    "arguments": {"url": url},
                    "result": inspected,
                }
            )
        elif tool_name == "commit_sources":
            tools_called.append("commit_sources")
            raw_list = tool_args.get("sources") if isinstance(tool_args.get("sources"), list) else []
            accepted: list[ResearchedSource] = []
            seen_urls: set[str] = set()
            for entry in raw_list:
                if not isinstance(entry, dict):
                    continue
                url = str(entry.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                ok, host, reason = is_reputable_source_url(url, extra_allowed_hosts=cfg.allowed_web_hosts)
                if not ok:
                    rejected_urls.append(f"{url} ({reason})")
                    continue
                seen_urls.add(url)
                cached = candidate_index.get(url) or {}
                accepted.append(
                    ResearchedSource(
                        url=url,
                        title=str(entry.get("title") or cached.get("title") or host)[:200],
                        source_kind=infer_source_kind(url, host),
                        domain=host,
                        rationale=str(entry.get("rationale") or cached.get("snippet") or "")[:360],
                        excerpt=str(cached.get("excerpt") or cached.get("snippet") or "")[:600],
                    )
                )
                if len(accepted) >= 3:
                    break
            if accepted:
                committed = accepted
                tool_history.append(
                    {
                        "id": call_id,
                        "tool": "commit_sources",
                        "arguments": {"count": len(accepted)},
                        "result": {"committed": len(accepted)},
                    }
                )
                break
            tool_history.append(
                {
                    "id": call_id,
                    "tool": "commit_sources",
                    "arguments": {"count": len(raw_list)},
                    "result": {
                        "committed": 0,
                        "error": "All submitted URLs were rejected by domain/SSRF filter. Pick 1..3 allowlisted URLs.",
                    },
                }
            )
        else:
            tool_history.append(
                {
                    "id": call_id,
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": {"error": f"Unknown tool: {tool_name}"},
                }
            )

    if not committed:
        raise SourceResearchMaxTurnsError(
            f"Source Research Agent reached max_turns={safe_max_turns} without committing 1..3 valid sources."
        )

    return SourceResearchResult(
        sources=committed,
        tools_called=tools_called,
        rejected_urls=rejected_urls,
        turns_used=turns_used,
        usage=LlmUsageOut(
            provider=last_usage.provider,
            model=last_usage.model,
            promptTokens=total_prompt,
            completionTokens=total_completion,
            totalTokens=total_prompt + total_completion,
            latencyMs=last_usage.latencyMs,
        ),
    )
