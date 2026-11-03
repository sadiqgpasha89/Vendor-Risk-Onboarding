"""Document parser with multi-format support and confidence estimation."""

import os
import io
import json
import logging
from typing import Dict, Any, List, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


class DocumentParser:
    """Extracts text, metadata, and structured fields from vendor documents."""

    @staticmethod
    def parse_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Parse raw document bytes into extracted text, tables, and confidence metrics."""
        ext = os.path.splitext(filename)[-1].lower()

        if ext in (".txt", ".md", ".log"):
            return DocumentParser._parse_text(file_bytes, filename)
        elif ext in (".json",):
            return DocumentParser._parse_json(file_bytes, filename)
        elif ext in (".csv", ".tsv"):
            return DocumentParser._parse_csv(file_bytes, filename, sep="," if ext == ".csv" else "\t")
        elif ext in (".xlsx", ".xls"):
            return DocumentParser._parse_excel(file_bytes, filename)
        elif ext in (".pdf",):
            return DocumentParser._parse_pdf(file_bytes, filename)
        else:
            # Fallback treat as text
            return DocumentParser._parse_text(file_bytes, filename)

    @staticmethod
    def _parse_text(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1", errors="replace")

        return {
            "filename": filename,
            "raw_text": text,
            "page_count": 1,
            "confidence": 0.98,
            "tables": [],
            "metadata": {"char_count": len(text), "lines": text.count("\n")},
        }

    @staticmethod
    def _parse_json(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        try:
            data = json.loads(file_bytes.decode("utf-8"))
            formatted = json.dumps(data, indent=2)
            return {
                "filename": filename,
                "raw_text": formatted,
                "parsed_json": data,
                "page_count": 1,
                "confidence": 1.0,
                "tables": [],
                "metadata": {"keys": list(data.keys()) if isinstance(data, dict) else []},
            }
        except Exception as e:
            return DocumentParser._parse_text(file_bytes, filename)

    @staticmethod
    def _parse_csv(file_bytes: bytes, filename: str, sep: str = ",") -> Dict[str, Any]:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), sep=sep)
            records = df.head(100).to_dict(orient="records")
            text_repr = df.to_string()
            return {
                "filename": filename,
                "raw_text": text_repr,
                "page_count": 1,
                "confidence": 0.95,
                "tables": [records],
                "metadata": {"rows": len(df), "columns": list(df.columns)},
            }
        except Exception as e:
            return DocumentParser._parse_text(file_bytes, filename)

    @staticmethod
    def _parse_excel(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        try:
            dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
            all_tables = []
            text_parts = []
            for sheet_name, df in dfs.items():
                text_parts.append(f"--- Sheet: {sheet_name} ---\n" + df.to_string())
                all_tables.append(df.head(50).to_dict(orient="records"))

            return {
                "filename": filename,
                "raw_text": "\n\n".join(text_parts),
                "page_count": len(dfs),
                "confidence": 0.93,
                "tables": all_tables,
                "metadata": {"sheets": list(dfs.keys())},
            }
        except Exception as e:
            return DocumentParser._parse_text(file_bytes, filename)

    @staticmethod
    def _parse_pdf(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        text_content = []
        page_count = 1
        confidence = 0.88

        # Try pypdf
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            page_count = len(reader.pages)
            for i, page in enumerate(reader.pages):
                extracted = page.extract_text() or ""
                text_content.append(f"[Page {i+1}]\n{extracted}")
            full_text = "\n\n".join(text_content)
            if not full_text.strip():
                # Scanned PDF or empty text
                full_text = f"[Scanned PDF without text layer: {filename}]"
                confidence = 0.60
        except ImportError:
            try:
                full_text = file_bytes.decode("latin-1", errors="ignore")
                confidence = 0.50
            except Exception:
                full_text = f"[Binary PDF: {filename}]"
                confidence = 0.40

        return {
            "filename": filename,
            "raw_text": full_text,
            "page_count": page_count,
            "confidence": confidence,
            "tables": [],
            "metadata": {"is_scanned": confidence < 0.70},
        }
