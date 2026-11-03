"""Document Processor Agent: Ingests, parses, and extracts structured data from vendor documents."""

import json
import logging
from typing import Dict, Any, List
from src.agents.definitions import AgentState, Document
from src.data_engineering.document_pipeline import DocumentIngestionPipeline
from src.llmops.llm_gateway import llm_gateway
from src.llmops.tracer import trace_agent_execution

logger = logging.getLogger(__name__)


class DocumentProcessorAgent:
    """Agent responsible for document OCR, layout parsing, and key information extraction."""

    def __init__(self):
        self.pipeline = DocumentIngestionPipeline()

    @trace_agent_execution("DocumentProcessorAgent")
    async def process(self, state: AgentState) -> AgentState:
        """Process all documents in the workflow state."""
        logger.info(f"DocumentProcessorAgent: Processing {len(state.documents)} documents for vendor {state.vendor_id}")

        extracted_docs = []
        for doc in state.documents:
            file_bytes = doc.content.encode("utf-8") if isinstance(doc.content, str) else doc.content
            extracted = await self.pipeline.ingest_document(
                vendor_id=state.vendor_id,
                filename=doc.file_name,
                file_bytes=file_bytes,
            )
            extracted_docs.append(extracted.model_dump(mode="json"))
            doc.extracted_data = extracted.model_dump(mode="json")

        state.documents_processed = len(state.documents)

        # Use LLM gateway to extract deeper qualitative insights from the combined document texts
        combined_text = "\n\n".join(
            f"=== {d.file_name} ({d.document_type or 'General'}) ===\n{d.content[:3000]}"
            for d in state.documents
        )

        if combined_text.strip():
            prompt = f"""Analyze the following vendor documents and extract key structured information:

Documents:
{combined_text}

For each document:
1. Identify document type and official verification markers
2. Extract key financial figures (revenue, net income, assets, liabilities)
3. Identify operational risks, litigation, or regulatory red flags
4. Assess document authenticity and completeness

Provide a structured JSON response with keys: 'document_summary', 'extracted_metrics', 'findings', and 'authenticity_confidence'."""

            llm_response = await llm_gateway.invoke(prompt)
            state.agent_results["document_processing"] = {
                "extracted_docs": extracted_docs,
                "analysis": llm_response,
            }
        else:
            state.agent_results["document_processing"] = {
                "extracted_docs": extracted_docs,
                "analysis": "No document attachments provided for extraction.",
            }

        return state
