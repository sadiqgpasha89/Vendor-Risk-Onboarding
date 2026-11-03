"""Entity Resolution and Deduplication Engine using fuzzy and phonetic algorithms."""

import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class MatchCandidate:
    target_id: str
    target_name: str
    similarity_score: float
    match_type: str  # EXACT, PHONETIC, FUZZY
    is_duplicate: bool


class EntityResolutionEngine:
    """Detects duplicate suppliers, shell company variations, and sanction list hits."""

    def __init__(self, fuzzy_threshold: float = 0.85):
        self.fuzzy_threshold = fuzzy_threshold

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize business name by removing corporate legal designations, punctuation, and whitespace."""
        if not name:
            return ""
        name = name.lower()
        # Remove common corporate suffixes
        suffixes = [
            r"\binc\b\.?", r"\bincorporated\b", r"\bcorp\b\.?", r"\bcorporation\b",
            r"\bllc\b", r"\bltd\b\.?", r"\blimited\b", r"\bgmbh\b", r"\bplc\b",
            r"\bs\.?a\b", r"\bpvt\b\.?", r"\bco\b\.?", r"\bcompany\b"
        ]
        for s in suffixes:
            name = re.sub(s, "", name)
        # Remove non-alphanumeric characters
        name = re.sub(r"[^\w\s]", " ", name)
        return " ".join(name.split())

    @staticmethod
    def soundex(token: str) -> str:
        """Compute American Soundex phonetic representation of a word."""
        token = token.upper()
        token = re.sub(r"[^A-Z]", "", token)
        if not token:
            return "0000"

        mapping = {
            "B": "1", "F": "1", "P": "1", "V": "1",
            "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
            "D": "3", "T": "3",
            "L": "4",
            "M": "5", "N": "5",
            "R": "6",
        }

        first_char = token[0]
        encoded = [first_char]
        prev_code = mapping.get(first_char, "0")

        for ch in token[1:]:
            code = mapping.get(ch, "0")
            if code != "0" and code != prev_code:
                encoded.append(code)
                if len(encoded) == 4:
                    break
            prev_code = code

        while len(encoded) < 4:
            encoded.append("0")

        return "".join(encoded[:4])

    @staticmethod
    def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1) -> float:
        """Calculate Jaro-Winkler string similarity score between 0.0 and 1.0."""
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        len1, len2 = len(s1), len(s2)
        match_window = max(len1, len2) // 2 - 1

        matches1 = [False] * len1
        matches2 = [False] * len2
        matches = 0

        for i in range(len1):
            start = max(0, i - match_window)
            end = min(i + match_window + 1, len2)
            for j in range(start, end):
                if not matches2[j] and s1[i] == s2[j]:
                    matches1[i] = True
                    matches2[j] = True
                    matches += 1
                    break

        if matches == 0:
            return 0.0

        # Transpositions
        k = 0
        transpositions = 0
        for i in range(len1):
            if matches1[i]:
                while not matches2[k]:
                    k += 1
                if s1[i] != s2[k]:
                    transpositions += 1
                k += 1

        transpositions //= 2
        jaro = (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0

        # Common prefix length up to 4 chars
        prefix = 0
        for i in range(min(len1, len2, 4)):
            if s1[i] == s2[i]:
                prefix += 1
            else:
                break

        return jaro + prefix * p * (1.0 - jaro)

    def compare_entities(
        self,
        query_name: str,
        target_name: str,
        query_tax_id: Optional[str] = None,
        target_tax_id: Optional[str] = None,
    ) -> Tuple[float, str]:
        """Compute composite matching score between two entity profiles."""
        # Exact tax ID match is an immediate 1.0 collision
        if query_tax_id and target_tax_id:
            clean_q_tax = re.sub(r"[\s\-_]", "", query_tax_id).upper()
            clean_t_tax = re.sub(r"[\s\-_]", "", target_tax_id).upper()
            if clean_q_tax == clean_t_tax:
                return 1.0, "EXACT_TAX_ID_MATCH"

        norm_q = self.normalize_name(query_name)
        norm_t = self.normalize_name(target_name)

        if norm_q == norm_t and norm_q:
            return 1.0, "EXACT_NORMALIZED_NAME_MATCH"

        # Check phonetic match
        q_tokens = norm_q.split()
        t_tokens = norm_t.split()
        if q_tokens and t_tokens:
            q_soundex = " ".join(self.soundex(tok) for tok in q_tokens)
            t_soundex = " ".join(self.soundex(tok) for tok in t_tokens)
            if q_soundex == t_soundex:
                return 0.95, "PHONETIC_MATCH"

        # Fuzzy similarity
        similarity = self.jaro_winkler_similarity(norm_q, norm_t)
        return similarity, "FUZZY_STRING_MATCH"

    def match_against_registry(
        self,
        query_name: str,
        query_tax_id: Optional[str] = None,
        known_registry: Optional[List[Dict[str, Any]]] = None,
    ) -> List[MatchCandidate]:
        """Screen query against known vendors or sanctions watchlist."""
        candidates = []
        registry = known_registry or []
        for record in registry:
            target_name = record.get("name") or record.get("legal_name", "")
            target_tax = record.get("registration_number") or record.get("tax_id")
            target_id = record.get("id") or record.get("entry_id", "unknown")

            score, match_type = self.compare_entities(query_name, target_name, query_tax_id, target_tax)

            if score >= self.fuzzy_threshold:
                candidates.append(
                    MatchCandidate(
                        target_id=str(target_id),
                        target_name=target_name,
                        similarity_score=score,
                        match_type=match_type,
                        is_duplicate=score >= 0.92,
                    )
                )

        candidates.sort(key=lambda c: c.similarity_score, reverse=True)
        return candidates

    # Aliases
    normalize_entity_name = normalize_name
    jaro_winkler = jaro_winkler_similarity

