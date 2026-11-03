"""RAG: eight chunking strategies + router, hashing embedder, hybrid retrieval (dense + BM25 -> RRF -> rerank -> parent expansion).

Plan §6.3. Tenant and vendor filters are applied INSIDE the retrieval service, never trusted from a prompt (GR-009).
Citations are mechanical: every hit carries chunk_id, doc_id, page range and section path.

Honest notes on stand-ins (see docs/BUILD_LOG.md): the embedder is a deterministic hashing-trick vectoriser behind the
`Embedder` interface (swap for a real model); `late` chunking is approximated by blending a document-level context vector
into each chunk vector; the reranker is a lexical cross-scorer. Strategy choice should come from the bake-off in evals/.
"""
from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from .store import Store
from .util import sha256_text

CHUNKER_VERSION = "chunkers-1.0"
WORD = re.compile(r"\w+", re.U)
HEADING = re.compile(
    r"^(?:#{1,4}\s+.+|(?:section\s+)?\d+(?:\.\d+)*[.)]?\s+[A-Z][^\n]{2,90}|[IVX]{1,5}\.\s+[A-Z][^\n]{2,90}|"
    r"[A-Z][A-Z0-9 \-/&,]{4,70})$")
CRITICAL = re.compile(r"(opinion|scope|excluded|carve|exception|deviation|RTO|RPO|recovery time|liabilit|audit right|"
                      r"right to audit|breach|notif|sub-?processor|sub-?contract|going concern|qualified|insured|limit of)", re.I)
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def toks(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s)]


@dataclass
class DocInput:
    doc_id: str
    doc_type: str
    pages: list[str]


@dataclass
class Chunk:
    doc_id: str
    strategy: str
    text: str
    page_from: int
    page_to: int
    section_path: str = "doc"
    level: int = 2
    ordinal: int = 0
    parent_ordinal: int | None = None      # index into the chunk list for the parent
    meta: dict = field(default_factory=dict)
    chunk_id: str = ""
    parent_chunk_id: str | None = None

    @property
    def token_count(self) -> int:
        return len(toks(self.text))


def _cid(doc_id: str, strategy: str, ordinal: int, text: str) -> str:
    return "ch_" + sha256_text(f"{CHUNKER_VERSION}|{doc_id}|{strategy}|{ordinal}|{text[:80]}")[:16]


def _finalise(chunks: list[Chunk]) -> list[Chunk]:
    for i, c in enumerate(chunks):
        c.ordinal = i
        c.chunk_id = _cid(c.doc_id, c.strategy, i, c.text)
    for c in chunks:
        if c.parent_ordinal is not None:
            c.parent_chunk_id = chunks[c.parent_ordinal].chunk_id
    return chunks


def _lines(doc: DocInput):
    for pn, page in enumerate(doc.pages, 1):
        for ln in page.split("\n"):
            if ln.strip():
                yield pn, ln.rstrip()


def _words_with_pages(doc: DocInput) -> list[tuple[str, int]]:
    return [(w, pn) for pn, page in enumerate(doc.pages, 1) for w in page.split()]


# --------------------------------------------------------------------------------- strategies
class Chunker(Protocol):
    name: str
    def chunk(self, doc: DocInput) -> list[Chunk]: ...


class FixedChunker:
    name = "fixed"
    def __init__(self, size: int = 180, overlap: int = 20):
        self.size, self.overlap = size, overlap
    def chunk(self, doc):
        ws, out, i = _words_with_pages(doc), [], 0
        step = max(1, self.size - self.overlap)
        while i < len(ws):
            seg = ws[i:i + self.size]
            out.append(Chunk(doc.doc_id, self.name, " ".join(w for w, _ in seg), seg[0][1], seg[-1][1]))
            i += step
        return _finalise(out)


class RecursiveChunker:
    name = "recursive"
    SEPS = ["\n\n", "\n", ". ", " "]
    def __init__(self, size: int = 180):
        self.size = size
    def _split(self, text: str, sep_i: int) -> list[str]:
        if len(toks(text)) <= self.size or sep_i >= len(self.SEPS):
            return [text]
        parts = [p for p in text.split(self.SEPS[sep_i]) if p.strip()]
        if len(parts) == 1:
            return self._split(text, sep_i + 1)
        out, buf = [], ""
        for p in parts:
            cand = (buf + self.SEPS[sep_i] + p) if buf else p
            if len(toks(cand)) <= self.size:
                buf = cand
            else:
                if buf:
                    out.append(buf)
                out.extend(self._split(p, sep_i + 1) if len(toks(p)) > self.size else [p])
                buf = ""
        if buf:
            out.append(buf)
        return out
    def chunk(self, doc):
        out = []
        for pn, page in enumerate(doc.pages, 1):
            for seg in self._split(page, 0):
                if seg.strip():
                    out.append(Chunk(doc.doc_id, self.name, seg.strip(), pn, pn))
        return _finalise(out)


def _sections(doc: DocInput) -> list[dict]:
    """Split into sections at heading lines. Each: {path, level, start_page, end_page, lines:[(page,text)]}."""
    secs, stack = [], []
    cur = {"path": "preamble", "level": 1, "p0": 1, "p1": 1, "lines": []}
    for pn, ln in _lines(doc):
        s = ln.strip()
        if HEADING.match(s) and len(s) < 100:
            if cur["lines"]:
                secs.append(cur)
            title = re.sub(r"^#+\s*", "", s)
            m = re.match(r"^(?:section\s+)?(\d+(?:\.\d+)*)", title, re.I)
            depth = (m.group(1).count(".") + 1) if m else 1
            stack = stack[:depth - 1] + [title]
            cur = {"path": " > ".join(stack), "level": depth, "p0": pn, "p1": pn, "lines": []}
        else:
            cur["lines"].append((pn, ln))
            cur["p1"] = pn
    if cur["lines"]:
        secs.append(cur)
    return secs


class DocumentChunker:
    name = "document_based"
    def __init__(self, max_tokens: int = 400):
        self.max_tokens = max_tokens
    def chunk(self, doc):
        out = []
        for s in _sections(doc):
            text = "\n".join(t for _, t in s["lines"])
            if len(toks(text)) <= self.max_tokens:
                out.append(Chunk(doc.doc_id, self.name, f"{s['path']}\n{text}", s["p0"], s["p1"], s["path"]))
            else:
                sub = RecursiveChunker(self.max_tokens // 2).chunk(DocInput(doc.doc_id, doc.doc_type, [text]))
                for c in sub:
                    out.append(Chunk(doc.doc_id, self.name, f"{s['path']}\n{c.text}", s["p0"], s["p1"], s["path"]))
        return _finalise(out)


class HierarchicalChunker:
    """doc -> section -> paragraph. Leaves are indexed; parents are returned on expansion (plan §6.3.2 #8)."""
    name = "hierarchical"
    def chunk(self, doc):
        out: list[Chunk] = []
        for s in _sections(doc):
            text = "\n".join(t for _, t in s["lines"])
            parent = Chunk(doc.doc_id, self.name, f"{s['path']}\n{text}"[:12000], s["p0"], s["p1"], s["path"], level=1,
                           meta={"indexable": False})
            out.append(parent)
            pi = len(out) - 1
            para, para_p = [], s["p0"]
            def flush():
                nonlocal para
                if para:
                    out.append(Chunk(doc.doc_id, self.name, " ".join(para), para_p, para_p, s["path"], level=2, parent_ordinal=pi))
                    para = []
            for pn, ln in s["lines"]:
                if not para:
                    para_p = pn
                para.append(ln.strip())
                if len(toks(" ".join(para))) >= 90 or ln.rstrip().endswith((".", ":")) and len(toks(" ".join(para))) >= 25:
                    flush()
            flush()
        return _finalise(out)


def _sentences(doc: DocInput) -> list[tuple[str, int, str]]:
    out = []
    sec = "doc"
    for s in _sections(doc):
        sec = s["path"]
        buf, pg = [], s["p0"]
        text = " ".join(t.strip() for _, t in s["lines"])
        for sent in SENT.split(text):
            if sent.strip():
                out.append((sent.strip(), pg, sec))
        # best-effort page attribution: map sentence to first page containing its prefix
    for i, (sent, _, sec) in enumerate(out):
        for pn, page in enumerate(doc.pages, 1):
            if sent[:40] in page.replace("\n", " "):
                out[i] = (sent, pn, sec)
                break
    return out


class SemanticChunker:
    name = "semantic"
    def __init__(self, embedder: "Embedder | None" = None, window: int = 3, min_tokens: int = 40, max_tokens: int = 320):
        self.emb = embedder or HashingEmbedder()
        self.window, self.min_tokens, self.max_tokens = window, min_tokens, max_tokens
    def chunk(self, doc):
        sents = _sentences(doc)
        if not sents:
            return []
        vecs = self.emb.embed([s for s, _, _ in sents])
        w = self.window
        sims = []
        for i in range(1, len(sents)):
            a = vecs[max(0, i - w):i].mean(axis=0)
            b = vecs[i:i + w].mean(axis=0)
            sims.append(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)))
        thr = (np.mean(sims) - 0.5 * np.std(sims)) if sims else 0.0
        out, cur = [], [sents[0]]
        for i in range(1, len(sents)):
            n = sum(len(toks(s)) for s, _, _ in cur)
            if (sims[i - 1] < thr and n >= self.min_tokens) or n >= self.max_tokens or sents[i][2] != cur[-1][2] and n >= self.min_tokens:
                out.append(self._mk(doc, cur)); cur = []
            cur.append(sents[i])
        if cur:
            out.append(self._mk(doc, cur))
        return _finalise(out)
    def _mk(self, doc, cur):
        return Chunk(doc.doc_id, self.name, " ".join(s for s, _, _ in cur), cur[0][1], cur[-1][1], cur[0][2])


class PropositionChunker:
    """Atomic, standalone statements for CRITICAL facts only (opinion, scope, exceptions, RTO/RPO, liability caps...).
    Deterministic offline form; an LLM rewriter can be injected via `rewrite` to resolve pronouns/definitions."""
    name = "llm_propositions"
    def __init__(self, rewrite: Callable[[str, str], str] | None = None):
        self.rewrite = rewrite
    def chunk(self, doc):
        out = []
        for sent, pn, sec in _sentences(doc):
            if CRITICAL.search(sent):
                text = self.rewrite(sent, sec) if self.rewrite else f"[{sec}, p.{pn}] {sent}"
                out.append(Chunk(doc.doc_id, self.name, text, pn, pn, sec, meta={"proposition": True}))
        return _finalise(out)


class LateChunker:
    """Approximation of late chunking: boundaries from document structure, vectors blended with a document-level
    context vector (definitions section / header) so cross-references keep context. See embed_chunks()."""
    name = "late"
    def chunk(self, doc):
        base = DocumentChunker(300).chunk(doc)
        context = " ".join(doc.pages[0].split()[:220]) if doc.pages else ""
        for c in base:
            c.strategy = self.name
            c.meta = {"late_context": context, "embedding_mode": "late_pooled_approx"}
        return _finalise(base)


ROUTER_RULES = [   # plan §6.3.3 v1 defaults; overwrite with bake-off winners (evals/retrieval)
    ({"soc2_report"}, ["hierarchical", "semantic", "llm_propositions"]),
    ({"contract", "dpa", "msa"}, ["document_based", "hierarchical", "late"]),
    ({"policy", "control_library"}, ["document_based"]),
    ({"pentest_summary"}, ["hierarchical", "llm_propositions"]),
    ({"iso_certificate", "insurance_certificate"}, ["recursive", "llm_propositions"]),
    ({"financial_statements"}, ["document_based", "llm_propositions"]),
    ({"bcp_dr"}, ["hierarchical", "llm_propositions"]),
]
REGISTRY: dict[str, Callable[[], Chunker]] = {
    "fixed": FixedChunker, "recursive": RecursiveChunker, "document_based": DocumentChunker, "semantic": SemanticChunker,
    "llm_propositions": PropositionChunker, "late": LateChunker, "hierarchical": HierarchicalChunker,
}


class ChunkRouter:
    """Strategy #6 ('agentic'): picks strategies per doc type / OCR quality and records the choice."""
    name = "agentic_router"
    def __init__(self, rules=None, overrides: dict[str, list[str]] | None = None):
        self.rules, self.overrides = rules or ROUTER_RULES, overrides or {}
    def choose(self, doc: DocInput, ocr_quality: str = "high") -> list[str]:
        if doc.doc_type in self.overrides:
            return self.overrides[doc.doc_type]
        if ocr_quality == "low":
            return ["recursive"]
        for types, strategies in self.rules:
            if doc.doc_type in types:
                return strategies
        return ["recursive"]
    def chunk(self, doc: DocInput, ocr_quality: str = "high") -> list[Chunk]:
        chosen = self.choose(doc, ocr_quality)
        out: list[Chunk] = []
        for s in chosen:
            cs = REGISTRY[s]().chunk(doc)
            for c in cs:
                c.meta = {**c.meta, "router_choice": chosen}
            out.extend(cs)
        # re-key ids across strategies (ordinals must be unique per list); keep parent links per strategy
        by_strategy: dict[str, list[Chunk]] = {}
        for c in out:
            by_strategy.setdefault(c.strategy, []).append(c)
        return [c for s in chosen for c in by_strategy.get(s, [])]


# --------------------------------------------------------------------------------- embeddings
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    """Deterministic signed hashing-trick bag of unigrams+bigrams, L2-normalised. Offline stand-in for a real model."""
    def __init__(self, dim: int = 512):
        self.dim = dim
    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        t = toks(text)
        grams = t + [a + "_" + b for a, b in zip(t, t[1:])]
        for g in grams:
            h = zlib.crc32(g.encode())
            v[h % self.dim] += (1.0 if (h >> 16) & 1 else -1.0) * (1.0 if "_" not in g else 0.6)
        n = np.linalg.norm(v)
        return v / n if n else v
    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)


def embed_chunks(embedder: Embedder, chunks: list[Chunk]) -> np.ndarray:
    base = embedder.embed([c.text for c in chunks])
    for i, c in enumerate(chunks):
        ctx = c.meta.get("late_context")
        if ctx:
            v = base[i] + 0.35 * embedder.embed([ctx])[0]
            base[i] = v / (np.linalg.norm(v) + 1e-9)
    return base


# --------------------------------------------------------------------------------- index + search
@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    page_from: int
    page_to: int
    section_path: str
    text: str
    parent_text: str | None
    score: float
    strategy: str
    doc_type: str | None = None


class RetrievalIndex:
    def __init__(self, store: Store, embedder: Embedder | None = None, router: ChunkRouter | None = None):
        self.store = store
        self.emb = embedder or HashingEmbedder()
        self.router = router or ChunkRouter()

    def index_document(self, tenant_id: str, vendor_id: str, doc_id: str, doc_type: str, pages: list[str],
                       ocr_quality: str = "high") -> int:
        self.store.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))
        di = DocInput(doc_id, doc_type, pages)
        chunks = self.router.chunk(di, ocr_quality)
        if not chunks:
            return 0
        vecs = embed_chunks(self.emb, chunks)
        # map ids: parent links are per-strategy ordinals -> chunk ids already assigned in _finalise
        with self.store.tx():
            for c, v in zip(chunks, vecs):
                self.store.insert("doc_chunks", {
                    "chunk_id": c.chunk_id, "tenant_id": tenant_id, "doc_id": doc_id, "vendor_id": vendor_id,
                    "parent_chunk_id": c.parent_chunk_id, "level": c.level, "strategy": c.strategy, "section_path": c.section_path,
                    "page_from": c.page_from, "page_to": c.page_to, "text": c.text, "token_count": c.token_count,
                    "embedding": v.astype(np.float32).tobytes(), "meta": c.meta, "chunker_version": CHUNKER_VERSION})
        return len(chunks)

    # -- retrieval -----------------------------------------------------------------
    def _candidates(self, tenant_id: str, vendor_id: str, doc_types: list[str] | None, doc_ids: list[str] | None,
                    include_superseded: bool, query: str | None = None, qvec=None):
        if query is not None and hasattr(self.store, "candidate_rows"):      # PostgreSQL: pgvector ANN + GIN full-text pre-selection
            return self.store.candidate_rows(tenant_id, vendor_id, query, qvec, doc_types, doc_ids, include_superseded)
        sql = ("SELECT c.*, d.doc_type AS doc_type FROM doc_chunks c JOIN documents d ON d.doc_id=c.doc_id "
               "WHERE c.tenant_id=? AND c.vendor_id=?")
        params: list = [tenant_id, vendor_id]
        if not include_superseded:
            sql += " AND c.doc_id NOT IN (SELECT supersedes_doc_id FROM documents WHERE supersedes_doc_id IS NOT NULL)"
        if doc_types:
            sql += f" AND d.doc_type IN ({','.join('?' * len(doc_types))})"; params += doc_types
        if doc_ids:
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"; params += doc_ids
        rows = self.store.query(sql, params)
        return [r for r in rows if (r["meta"] or {}).get("indexable", True)]

    def search(self, tenant_id: str, vendor_id: str, query: str, k: int = 8, doc_types: list[str] | None = None,
               doc_ids: list[str] | None = None, include_superseded: bool = False, mode: str = "hybrid",
               rerank: bool = True) -> list[Hit]:
        qv = self.emb.embed([query])[0]
        rows = self._candidates(tenant_id, vendor_id, doc_types, doc_ids, include_superseded, query, qv)
        if not rows:
            return []
        mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        dense = mat @ qv
        dense_rank = list(np.argsort(-dense)[:40])
        lex = bm25_scores(query, [r["text"] for r in rows])
        lex_rank = [i for i in np.argsort(-lex)[:40] if lex[i] > 0]
        if mode == "dense":
            fused = {int(i): 1 / (60 + r) for r, i in enumerate(dense_rank, 1)}
        elif mode == "lexical":
            fused = {int(i): 1 / (60 + r) for r, i in enumerate(lex_rank, 1)}
        else:  # Reciprocal Rank Fusion
            fused = {}
            for ranking in (dense_rank, lex_rank):
                for r, i in enumerate(ranking, 1):
                    fused[int(i)] = fused.get(int(i), 0.0) + 1 / (60 + r)
        order = sorted(fused, key=lambda i: -fused[i])[:20]
        if rerank:
            order = sorted(order, key=lambda i: -(cross_score(query, rows[i]["text"]) + 0.15 * fused[i] * 60))[:k]
        else:
            order = order[:k]
        parents = {r["chunk_id"]: r for r in self.store.query(
            "SELECT chunk_id, text FROM doc_chunks WHERE chunk_id IN (%s)" % ",".join("?" * max(1, len({rows[i]['parent_chunk_id'] for i in order if rows[i]['parent_chunk_id']}))),
            list({rows[i]["parent_chunk_id"] for i in order if rows[i]["parent_chunk_id"]}) or [""])}
        hits, seen = [], set()
        for i in order:
            r = rows[i]
            if r["chunk_id"] in seen:
                continue
            seen.add(r["chunk_id"])
            hits.append(Hit(r["chunk_id"], r["doc_id"], r["page_from"], r["page_to"], r["section_path"], r["text"],
                            parents.get(r["parent_chunk_id"], {}).get("text") if r["parent_chunk_id"] else None,
                            float(fused[i]), r["strategy"], r["doc_type"]))
        return hits

    def get_chunk(self, tenant_id: str, vendor_id: str, chunk_id: str) -> dict | None:
        r = self.store.get("doc_chunks", "chunk_id", chunk_id)
        if r and r["tenant_id"] == tenant_id and r["vendor_id"] == vendor_id:
            return r
        return None


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    qt = list(dict.fromkeys(toks(query)))
    tdocs = [toks(d) for d in docs]
    n = len(docs)
    avg = (sum(len(t) for t in tdocs) / n) or 1.0
    df = {t: sum(1 for d in tdocs if t in set(d)) for t in qt}
    out = np.zeros(n)
    for i, d in enumerate(tdocs):
        tf: dict[str, int] = {}
        for w in d:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for t in qt:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        out[i] = s
    return out


STOP = {"the", "a", "an", "of", "is", "are", "to", "in", "and", "or", "for", "does", "do", "what", "which", "by", "on", "with", "as", "at", "be", "this", "that"}


def cross_score(query: str, text: str) -> float:
    """Lexical cross-scorer (stand-in for a cross-encoder): coverage of content terms + bigram + phrase proximity."""
    q = [t for t in toks(query) if t not in STOP]
    if not q:
        return 0.0
    tt = toks(text)
    ts = set(tt)
    cover = sum(1 for t in q if t in ts) / len(q)
    qb = {a + " " + b for a, b in zip(q, q[1:])}
    tb = {a + " " + b for a, b in zip(tt, tt[1:])}
    bigram = (len(qb & tb) / len(qb)) if qb else 0.0
    return cover + 0.5 * bigram
