"""Document Ingestion & OCR Processing Pipeline with Confidence Scoring."""

import os
import re
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.schemas.document import (
    DocumentCategory,
    ExtractedField,
    ExtractedDocumentData,
)
from src.utils.document_parser import DocumentParser
from src.core.cloud_adapters import get_storage_adapter

logger = logging.getLogger(__name__)


class DocumentIngestionPipeline:
    """Asynchronous pipeline to ingest, store, parse, and validate vendor documents."""

    def __init__(self, confidence_threshold: float = 0.85):
        self.confidence_threshold = confidence_threshold
        self.storage = get_storage_adapter()

    async def ingest_document(
        self,
        vendor_id: str,
        filename: str,
        file_bytes: bytes,
        category: DocumentCategory = DocumentCategory.OTHER,
    ) -> ExtractedDocumentData:
        """Ingest, store, parse and extract structured data from a vendor submission."""
        destination_path = f"{vendor_id}/{filename}"

        # 1. Persist to storage layer (Local / GCS)
        storage_uri = await self.storage.upload(file_bytes, destination_path)
        logger.info(f"Persisted document {filename} for vendor {vendor_id} to {storage_uri}")

        # 2. Parse document text & tables
        parsed = DocumentParser.parse_document(file_bytes, filename)
        raw_text = parsed.get("raw_text", "")
        base_confidence = parsed.get("confidence", 0.85)

        # 3. Categorize document if set to OTHER
        inferred_category = self._infer_category(filename, raw_text, category)

        # 4. Extract key financial & legal fields based on category
        fields = self._extract_domain_fields(raw_text, inferred_category, base_confidence)

        # 5. Calculate overall confidence score
        field_confidences = [f.confidence for f in fields.values()]
        overall_confidence = (
            sum(field_confidences) / len(field_confidences)
            if field_confidences
            else base_confidence
        )

        requires_validation = overall_confidence < self.confidence_threshold

        # 6. Detect document red flags
        red_flags = self._detect_document_red_flags(raw_text, overall_confidence)

        return ExtractedDocumentData(
            document_id=f"DOC-{abs(hash(destination_path)) % 1000000:06d}",
            vendor_id=vendor_id,
            category=inferred_category,
            overall_confidence=round(overall_confidence, 4),
            requires_manual_validation=requires_validation,
            fields=fields,
            tables=parsed.get("tables", []),
            raw_text=raw_text,
            red_flags=red_flags,
            extracted_at=datetime.utcnow(),
        )

    def _infer_category(self, filename: str, text: str, given: DocumentCategory) -> DocumentCategory:
        if given != DocumentCategory.OTHER:
            return given

        lowered_name = filename.lower()
        lowered_text = text[:1000].lower()

        if "incorporation" in lowered_name or "certificate of incorporation" in lowered_text:
            return DocumentCategory.CERTIFICATE_OF_INCORPORATION
        elif "tax" in lowered_name or "w-9" in lowered_name or "tax clearance" in lowered_text:
            return DocumentCategory.TAX_CLEARANCE_CERTIFICATE
        elif "financial" in lowered_name or "balance sheet" in lowered_text or "income statement" in lowered_text:
            return DocumentCategory.FINANCIAL_STATEMENT
        elif "iso" in lowered_name or "iso 9001" in lowered_text or "iso 27001" in lowered_text:
            return DocumentCategory.ISO_COMPLIANCE_CERTIFICATE
        elif "bank" in lowered_name or "voided check" in lowered_text or "iban confirmation" in lowered_text:
            return DocumentCategory.BANK_CONFIRMATION_LETTER
        elif "soc2" in lowered_name or "soc 2" in lowered_text:
            return DocumentCategory.SOC2_AUDIT_REPORT

        return DocumentCategory.OTHER

    def _extract_domain_fields(
        self,
        text: str,
        category: DocumentCategory,
        base_confidence: float,
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # Tax ID regex pattern (EIN: XX-XXXXXXX or 9 digits)
        tax_matches = re.findall(r"\b(\d{2}-\d{7}|\d{9})\b", text)
        if tax_matches:
            fields["tax_id"] = ExtractedField(
                field_name="tax_id",
                value=tax_matches[0],
                confidence=round(base_confidence * 0.98, 2),
                source_snippet=tax_matches[0],
            )

        # Revenue / net income extraction
        rev_match = re.search(r"(?:annual revenue|total revenue|gross revenue)[:\s]+(?:\$|USD)?\s*([\d,]+(?:\.\d{2})?)", text, re.IGNORECASE)
        if rev_match:
            try:
                num_val = float(rev_match.group(1).replace(",", ""))
                fields["annual_revenue"] = ExtractedField(
                    field_name="annual_revenue",
                    value=num_val,
                    confidence=round(base_confidence * 0.95, 2),
                    source_snippet=rev_match.group(0),
                )
            except ValueError:
                pass

        # Registration date
        date_match = re.search(r"(?:date of incorporation|registration date|incorporated on)[:\s]+([A-Za-z0-9\s,/-]{8,25})", text, re.IGNORECASE)
        if date_match:
            fields["incorporation_date"] = ExtractedField(
                field_name="incorporation_date",
                value=date_match.group(1).strip(),
                confidence=round(base_confidence * 0.90, 2),
                source_snippet=date_match.group(0),
            )

        # Bank Account / IBAN
        iban_match = re.search(r"\b([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b", text)
        if iban_match:
            fields["iban"] = ExtractedField(
                field_name="iban",
                value=iban_match.group(1),
                confidence=round(base_confidence * 0.97, 2),
                source_snippet=iban_match.group(0),
            )

        return fields

    def _detect_document_red_flags(self, text: str, confidence: float) -> List[str]:
        red_flags = []
        lowered = text.lower()

        if confidence < 0.70:
            red_flags.append(f"Low OCR extraction confidence ({confidence:.2f}). Document may be degraded or altered.")

        if "bankruptcy" in lowered or "chapter 11" in lowered:
            red_flags.append("Document references active or prior bankruptcy proceedings.")

        if "default" in lowered or "liquidation" in lowered:
            red_flags.append("Document mentions potential loan default or insolvency.")

        if "sanction" in lowered and "not subject to" not in lowered:
            red_flags.append("Document text contains explicit mentions of sanctions.")

        return red_flags
