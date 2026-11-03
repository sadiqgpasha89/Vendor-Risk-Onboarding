"""Sanctions/PEP screening, ownership aggregation and entity resolution (plan §4.2.3, §15.3.2).

Deterministic and recall-first (R1, GR-005): anything at/above REVIEW_FLOOR goes to a human; nothing above the floor is
auto-cleared. Pure stdlib (no rapidfuzz here): Jaro-Winkler, token-set ratio and Soundex are implemented below.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .util import canonical_json, sha256_text

LEGAL_SUFFIXES = {
    "llc", "ltd", "limited", "gmbh", "sa", "ag", "bv", "plc", "inc", "incorporated", "corp", "corporation", "co",
    "company", "pvt", "private", "llp", "lp", "nv", "srl", "sarl", "pte", "oy", "ab", "kg", "sas", "spa", "pjsc", "ooo", "jsc",
}
STOPWORDS = {"the", "and", "of", "for", "de", "la", "le", "el", "al"}
# Tokens too common to establish identity on their own (drives false-positive control).
GENERIC_TOKENS = {
    "trading", "group", "holdings", "holding", "international", "global", "services", "solutions", "systems", "technologies",
    "technology", "industries", "industrial", "enterprises", "partners", "capital", "bank", "trust", "financial", "logistics",
    "consulting", "resources", "energy", "petroleum", "shipping", "marine", "import", "export", "general", "united", "national",
    "first", "new", "pacific", "atlantic", "euro", "asia", "trade", "commerce", "investment", "investments", "development", "supply",
    "management", "network", "networks", "software", "data", "cloud", "digital", "payments", "payment", "processing", "mining", "oil", "gas",
}


def fold(tok: str) -> str:
    """Phonetic folding for transliteration drift (c/k, w/v, ph/f, y/i, z/s, x/ks, doubled letters). Used alongside, never instead of, raw matching."""
    t = tok.casefold()
    t = t.replace("ph", "f").replace("ck", "k").replace("q", "k").replace("x", "ks")
    t = re.sub(r"c(?=[eiy])", "s", t)
    t = t.replace("c", "k").replace("w", "v").replace("y", "i").replace("z", "s").replace("j", "i")
    return re.sub(r"(.)\1+", r"\1", t)


@dataclass
class NormName:
    raw: str
    tokens: list[str]
    distinctive: list[str]
    joined: str
    suffix: str | None = None
    ftokens: list[str] = field(default_factory=list)
    fjoined: str = ""
    fdistinctive: list[str] = field(default_factory=list)


def normalise(name: str) -> NormName:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    s = re.sub(r"[^\w\s]", " ", s.replace("&", " and "))
    raw_tokens = [t for t in s.split() if t]
    suffix = None
    tokens = []
    for t in raw_tokens:
        if t in LEGAL_SUFFIXES:
            suffix = suffix or t
            continue
        if t in STOPWORDS:
            continue
        tokens.append(t)
    if not tokens:  # name made only of suffix/stopwords; keep raw so we never match on emptiness
        tokens = raw_tokens or [""]
    tokens_sorted = sorted(tokens)
    distinctive = [t for t in tokens_sorted if t not in GENERIC_TOKENS] or []
    ft = sorted(fold(t) for t in tokens)
    fd = sorted(fold(t) for t in distinctive)
    return NormName(raw=name, tokens=tokens_sorted, distinctive=distinctive, joined=" ".join(tokens_sorted), suffix=suffix,
                    ftokens=ft, fjoined=" ".join(ft), fdistinctive=fd)


def jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if not l1 or not l2:
        return 0.0
    md = max(l1, l2) // 2 - 1
    m1, m2 = [False] * l1, [False] * l2
    matches = 0
    for i, c in enumerate(s1):
        for j in range(max(0, i - md), min(l2, i + md + 1)):
            if not m2[j] and s2[j] == c:
                m1[i] = m2[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t, k = 0, 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    t //= 2
    return (matches / l1 + matches / l2 + (matches - t) / matches) / 3


def jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    j = jaro(s1, s2)
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        prefix += 1
    return j + prefix * p * (1 - j)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if (a or b) else 0.0


def token_set_ratio(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    inter = " ".join(sorted(sa & sb))
    da, db = " ".join(sorted(sa - sb)), " ".join(sorted(sb - sa))
    s1, s2, s3 = inter, (inter + " " + da).strip(), (inter + " " + db).strip()
    if not inter:
        return _ratio(s2, s3)
    return max(_ratio(s1, s2), _ratio(s1, s3), _ratio(s2, s3))


def soundex(w: str) -> str:
    w = re.sub(r"[^a-z]", "", w.lower())
    if not w:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"),
             "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    out, last = w[0].upper(), codes.get(w[0], "")
    for ch in w[1:]:
        c = codes.get(ch, "")
        if c and c != last:
            out += c
        if ch not in "hw":
            last = c
    return (out + "000")[:4]


def phonetic_overlap(a: list[str], b: list[str]) -> float:
    sa, sb = {soundex(t) for t in a if t}, {soundex(t) for t in b if t}
    sa.discard(""); sb.discard("")
    return len(sa & sb) / max(len(sa), len(sb)) if sa and sb else 0.0


@dataclass
class MatchScore:
    score: float
    features: dict
    capped: bool = False
    matched_tokens: list[str] = field(default_factory=list)
    unmatched_query: list[str] = field(default_factory=list)
    unmatched_candidate: list[str] = field(default_factory=list)


def score_names(q: NormName, c: NormName, q_country: str | None, c_country: str | None, is_alias: bool = False) -> MatchScore:
    jw = max(jaro_winkler(q.joined, c.joined), jaro_winkler(q.fjoined, c.fjoined))
    ts = max(token_set_ratio(q.tokens, c.tokens), token_set_ratio(q.ftokens, c.ftokens))
    ph = max(phonetic_overlap(q.tokens, c.tokens), phonetic_overlap(q.ftokens, c.ftokens))
    if q_country and c_country:
        country = 1.0 if q_country.upper() == c_country.upper() else 0.0
    else:
        country = 0.5
    s = 0.40 * jw + 0.35 * ts + 0.15 * ph + 0.10 * country
    # False-positive control: sharing only generic words ("Global Trading ...") must not look like identity.
    capped = False
    if q.distinctive and c.distinctive:
        best = max(max(jaro_winkler(a, b) for a in q.distinctive for b in c.distinctive),
                   max(jaro_winkler(a, b) for a in q.fdistinctive for b in c.fdistinctive))
        if best < 0.85:
            s, capped = min(s, 0.60), True
    elif not q.distinctive or not c.distinctive:
        # one side is entirely generic words: weak evidence of identity unless the full strings are near-identical
        if jw < 0.97:
            s, capped = min(s, 0.60), True
    matched = sorted(t for t in q.tokens if any(jaro_winkler(t, u) >= 0.9 or jaro_winkler(fold(t), fold(u)) >= 0.9 for u in c.tokens))
    return MatchScore(
        score=round(s, 4),
        features={"jw": round(jw, 4), "token_set": round(ts, 4), "phonetic": round(ph, 4), "country": country, "alias_hit": is_alias},
        capped=capped, matched_tokens=matched,
        unmatched_query=[t for t in q.tokens if t not in matched],
        unmatched_candidate=[t for t in c.tokens if not any(jaro_winkler(t, u) >= 0.9 or jaro_winkler(fold(t), fold(u)) >= 0.9 for u in q.tokens)])


def explain(q_raw: str, cand_name: str, ms: MatchScore, list_name: str, list_version: str, matched_via_alias: bool) -> str:
    parts = [f"'{q_raw}' vs '{cand_name}' on {list_name} v{list_version[:8]}: score {ms.score:.2f}",
             f"(jw {ms.features['jw']:.2f}, token-set {ms.features['token_set']:.2f}, phonetic {ms.features['phonetic']:.2f}, country {ms.features['country']})"]
    if ms.matched_tokens:
        parts.append("matching tokens: " + ", ".join(ms.matched_tokens))
    if ms.unmatched_query or ms.unmatched_candidate:
        parts.append(f"differing tokens: query {ms.unmatched_query or '-'}, list {ms.unmatched_candidate or '-'}")
    if matched_via_alias:
        parts.append("matched via a listed alias")
    if ms.capped:
        parts.append("score capped: only generic words overlap")
    return "; ".join(parts) + "."


@dataclass
class Candidate:
    entity_id: str
    name: str
    matched_name: str
    program: str | None
    country: str | None
    entity_type: str | None
    score: float
    ms: MatchScore
    via_alias: bool


class SanctionsList:
    """In-memory list index with blocking (first-3-letters + soundex) for speed. Synthetic lists are labelled SYNTHETIC."""

    def __init__(self, name: str, entities: list[dict], source: str = "SYNTHETIC"):
        self.name = name
        self.source = source
        self.entities = {e["entity_id"]: e for e in entities}
        self.version = sha256_text(canonical_json(sorted(entities, key=lambda e: e["entity_id"])))[:16]
        self._names: list[tuple[str, NormName, bool]] = []   # entity_id, norm, is_alias
        self._blocks: dict[str, set[int]] = {}
        for e in entities:
            for i, nm in enumerate([e["name"]] + list(e.get("aliases", []))):
                n = normalise(nm)
                idx = len(self._names)
                self._names.append((e["entity_id"], n, i > 0))
                for t in n.tokens:
                    for key in self._keys(t):
                        self._blocks.setdefault(key, set()).add(idx)

    @staticmethod
    def _keys(tok: str) -> set[str]:
        ft = fold(tok)
        keys = {"p:" + tok[:3], "s:" + soundex(tok), "p:" + ft[:3], "s:" + soundex(ft)}
        return {k for k in keys if k not in ("p:", "s:")}

    @classmethod
    def load(cls, path: str) -> "SanctionsList":
        d = json.loads(Path(path).read_text())
        return cls(d.get("list_name", "SYNTHETIC_SDN"), d["entities"], d.get("source", "SYNTHETIC"))

    def screen(self, name: str, country: str | None = None, top_n: int = 3) -> list[Candidate]:
        q = normalise(name)
        idxs: set[int] = set()
        for t in q.tokens:
            for key in self._keys(t):
                idxs |= self._blocks.get(key, set())
        best: dict[str, Candidate] = {}
        for i in idxs:
            eid, cn, is_alias = self._names[i]
            e = self.entities[eid]
            ms = score_names(q, cn, country, e.get("country"), is_alias)
            cur = best.get(eid)
            if cur is None or ms.score > cur.score:
                best[eid] = Candidate(eid, e["name"], cn.raw, e.get("program"), e.get("country"), e.get("type"), ms.score, ms, is_alias)
        return sorted(best.values(), key=lambda c: -c.score)[:top_n]


# --------------------------------------------------------------------------- ownership graph
def effective_ownership(edges: list[dict], subject: str, max_depth: int = 6) -> dict[str, float]:
    """Effective % ownership of each ancestor of `subject` (sum over paths of product of stakes). edges: child_name,parent_name,pct."""
    by_child: dict[str, list[dict]] = {}
    for e in edges:
        by_child.setdefault(normalise(e["child_name"]).joined, []).append(e)
    result: dict[str, float] = {}

    def walk(node: str, acc: float, depth: int, seen: frozenset):
        if depth > max_depth:
            return
        for e in by_child.get(normalise(node).joined, []):
            p = e["parent_name"]
            key = normalise(p).joined
            if key in seen:
                continue  # cycle guard
            eff = acc * float(e["pct"]) / 100.0
            result[p] = result.get(p, 0.0) + eff * 100.0
            walk(p, eff, depth + 1, seen | {key})

    walk(subject, 1.0, 1, frozenset({normalise(subject).joined}))
    return {k: round(min(v, 100.0), 2) for k, v in result.items()}


@dataclass
class ScreenSubject:
    name: str
    role: str                  # vendor|trade_name|director|owner|ultimate_owner|subcontractor
    country: str | None = None
    pct: float | None = None


def build_subjects(intake: dict, edges: list[dict], ubo_threshold: float = 25.0) -> tuple[list[ScreenSubject], dict[str, float]]:
    subs = [ScreenSubject(intake["legal_name"], "vendor", intake.get("country_iso2"))]
    subs += [ScreenSubject(t, "trade_name", intake.get("country_iso2")) for t in intake.get("trade_names", [])]
    subs += [ScreenSubject(d, "director") for d in intake.get("directors", [])]
    eff = effective_ownership(edges, intake["legal_name"])
    seen = set()
    for o in intake.get("declared_owners", []):
        seen.add(normalise(o["name"]).joined)
        subs.append(ScreenSubject(o["name"], "owner", o.get("country_iso2"), o.get("pct")))
    for name, pct in eff.items():
        if normalise(name).joined in seen:
            continue
        subs.append(ScreenSubject(name, "ultimate_owner" if pct >= ubo_threshold else "owner", None, pct))
    subs += [ScreenSubject(s, "subcontractor") for s in intake.get("subcontractors", [])]
    return subs, eff


def screen_case(intake: dict, edges: list[dict], sl: SanctionsList, review_floor: float,
                ubo_threshold: float = 25.0, aggregate_threshold: float = 50.0) -> list[dict]:
    """Returns one record per subject (top candidate always recorded for audit) plus an ownership-aggregate record."""
    subjects, eff = build_subjects(intake, edges, ubo_threshold)
    results, flagged_pct = [], 0.0
    # direct declared stake percentages join the effective map (declared owners with no edge data)
    stakes = dict(eff)
    for o in intake.get("declared_owners", []):
        stakes[o["name"]] = max(stakes.get(o["name"], 0.0), float(o["pct"]))
    for s in subjects:
        cands = sl.screen(s.name, s.country)
        top = cands[0] if cands else None
        potential = bool(top and top.score >= review_floor)
        rec = {
            "subject_name": s.name, "subject_role": s.role, "list_name": sl.name, "list_version": sl.version,
            "match_entity_id": top.entity_id if top else None, "match_name": top.name if top else None,
            "score": top.score if top else 0.0, "features": top.ms.features if top else {},
            "auto_disposition": "POTENTIAL_MATCH" if potential else "NO_CANDIDATE",
            "explanation": explain(s.name, top.matched_name, top.ms, sl.name, sl.version, top.via_alias) if top else "No candidate on list.",
            "ownership_pct": stakes.get(s.name, s.pct),
            "program": top.program if top else None,
        }
        if potential and s.role in ("owner", "ultimate_owner"):
            flagged_pct += stakes.get(s.name, s.pct or 0.0)
        results.append(rec)
    if flagged_pct >= aggregate_threshold:
        results.append({
            "subject_name": intake["legal_name"], "subject_role": "ownership_aggregate", "list_name": sl.name,
            "list_version": sl.version, "match_entity_id": None, "match_name": None, "score": 1.0, "features": {"aggregate_pct": flagged_pct},
            "auto_disposition": "POTENTIAL_MATCH",
            "explanation": f"OFAC-style 50 Percent Rule: owners with potential list matches aggregate {flagged_pct:.1f}% >= {aggregate_threshold:.0f}% ownership of the vendor.",
            "ownership_pct": flagged_pct, "program": None})
    return results


# --------------------------------------------------------------------------- entity resolution
def resolve_entity(intake: dict, master: list[dict]) -> dict:
    """Candidates from the vendor master with link probability. p>=0.95 auto-link, 0.70..0.95 human confirm (G0), <0.70 new."""
    q = normalise(intake["legal_name"])
    q_domain = re.sub(r"^https?://(www\.)?", "", (intake.get("website") or "").lower()).split("/")[0]
    out = []
    for v in master:
        c = normalise(v["legal_name"])
        reg_match = bool(intake.get("registration_number") and v.get("reg_number") and intake["registration_number"].strip() == v["reg_number"].strip())
        lei_match = bool(intake.get("lei") and v.get("lei") and intake["lei"] == v["lei"])
        base = 0.55 * jaro_winkler(q.joined, c.joined) + 0.45 * token_set_ratio(q.tokens, c.tokens)
        p = base ** 3
        if v.get("country_iso2") and intake.get("country_iso2") and v["country_iso2"] != intake["country_iso2"]:
            p *= 0.6
        v_domain = re.sub(r"^https?://(www\.)?", "", (v.get("website") or "").lower()).split("/")[0]
        if q_domain and v_domain and q_domain == v_domain:
            p = min(1.0, p + 0.25)
        if reg_match or lei_match:
            p = max(p, 0.99)
        out.append({"vendor_id": v["vendor_id"], "legal_name": v["legal_name"], "p": round(min(p, 1.0), 4),
                    "reg_match": reg_match, "lei_match": lei_match})
    out.sort(key=lambda x: -x["p"])
    top = out[0] if out else None
    if top and top["p"] >= 0.95:
        decision = "AUTO_LINK"
    elif top and top["p"] >= 0.70:
        decision = "HUMAN_CONFIRM"
    else:
        decision = "NEW_VENDOR"
    return {"decision": decision, "candidates": out[:5], "top": top}
