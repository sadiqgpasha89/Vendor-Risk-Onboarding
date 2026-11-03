"""RAG Engine - Robust Retrieval-Augmented Generation with vector stores and semantic search."""

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
from abc import ABC, abstractmethod

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma, FAISS
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter, CharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter, CharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


@dataclass
class RetrievalMetrics:
    """Metrics for retrieval operations."""

    query: str
    retrieval_time: float = 0.0
    document_count: int = 0
    relevance_scores: List[float] = field(default_factory=list)
    avg_relevance: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RAGContext:
    """Context for RAG operations."""

    query: str
    retrieved_docs: List[Document] = field(default_factory=list)
    retrieved_chunks: List[str] = field(default_factory=list)
    relevance_scores: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    metrics: Optional[RetrievalMetrics] = None

    def get_context_string(self, max_length: int = 4000) -> str:
        """Format retrieved documents as context string."""
        context_parts = []
        total_length = 0

        for doc, score in zip(self.retrieved_docs, self.relevance_scores):
            doc_text = f"[Score: {score:.2f}] {doc.page_content}"
            if total_length + len(doc_text) > max_length:
                break
            context_parts.append(doc_text)
            total_length += len(doc_text)

        return "\n\n---\n\n".join(context_parts)


class VectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    async def add_documents(self, documents: List[Document]) -> None:
        """Add documents to vector store."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        k: int = 5,
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents."""
        pass

    @abstractmethod
    async def delete(self, document_ids: List[str]) -> None:
        """Delete documents from vector store."""
        pass

    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        pass


class ChromaVectorStore(VectorStore):
    """Chroma vector store implementation."""

    def __init__(
        self,
        collection_name: str,
        embedding_function: Optional[Embeddings] = None,
        persist_directory: Optional[str] = None,
    ):
        """Initialize Chroma vector store.

        Args:
            collection_name: Name of the collection
            embedding_function: Embedding function (uses OpenAI by default)
            persist_directory: Directory to persist data
        """
        self.collection_name = collection_name
        self.embedding_function = embedding_function or OpenAIEmbeddings()
        self.persist_directory = persist_directory

        self.store = Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding_function,
            persist_directory=persist_directory,
        )
        logger.info(f"Initialized Chroma vector store: {collection_name}")

    async def add_documents(self, documents: List[Document]) -> None:
        """Add documents to vector store."""
        try:
            ids = [f"{self.collection_name}_{i}" for i in range(len(documents))]
            self.store.add_documents(documents, ids=ids)
            logger.info(f"Added {len(documents)} documents to {self.collection_name}")
        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            raise

    async def search(
        self,
        query: str,
        k: int = 5,
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents."""
        try:
            results = self.store.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    async def delete(self, document_ids: List[str]) -> None:
        """Delete documents from vector store."""
        try:
            self.store.delete(ids=document_ids)
            logger.info(f"Deleted {len(document_ids)} documents")
        except Exception as e:
            logger.error(f"Error deleting documents: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        try:
            count = self.store._collection.count()
            return {
                "store_type": "chroma",
                "collection_name": self.collection_name,
                "document_count": count,
                "persist_directory": self.persist_directory,
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


class FAISSVectorStore(VectorStore):
    """FAISS vector store implementation."""

    def __init__(
        self,
        store_name: str,
        embedding_function: Optional[Embeddings] = None,
        index_path: Optional[str] = None,
    ):
        """Initialize FAISS vector store.

        Args:
            store_name: Name of the store
            embedding_function: Embedding function
            index_path: Path to save/load index
        """
        self.store_name = store_name
        self.embedding_function = embedding_function or OpenAIEmbeddings()
        self.index_path = index_path
        self.store = None
        self.document_map = {}

        if index_path:
            try:
                self.store = FAISS.load_local(
                    index_path,
                    embedding_function,
                    allow_dangerous_deserialization=True,
                )
                logger.info(f"Loaded FAISS index from {index_path}")
            except Exception as e:
                logger.warning(f"Could not load FAISS index: {e}")

    async def add_documents(self, documents: List[Document]) -> None:
        """Add documents to vector store."""
        try:
            if self.store is None:
                self.store = FAISS.from_documents(
                    documents,
                    self.embedding_function,
                )
            else:
                self.store.add_documents(documents)

            for i, doc in enumerate(documents):
                doc_id = f"{self.store_name}_{i}"
                self.document_map[doc_id] = doc

            if self.index_path:
                self.store.save_local(self.index_path)

            logger.info(f"Added {len(documents)} documents to FAISS store")
        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            raise

    async def search(
        self,
        query: str,
        k: int = 5,
    ) -> List[Tuple[Document, float]]:
        """Search for similar documents."""
        if self.store is None:
            return []

        try:
            results = self.store.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    async def delete(self, document_ids: List[str]) -> None:
        """Delete documents from vector store."""
        for doc_id in document_ids:
            if doc_id in self.document_map:
                del self.document_map[doc_id]

    async def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        return {
            "store_type": "faiss",
            "store_name": self.store_name,
            "document_count": len(self.document_map),
            "index_path": self.index_path,
        }


class DocumentProcessor:
    """Process and prepare documents for RAG."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n",
    ):
        """Initialize document processor.

        Args:
            chunk_size: Size of chunks
            chunk_overlap: Overlap between chunks
            separator: Separator for splitting
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", separator, ""],
        )

    async def process_documents(
        self,
        documents: List[Document],
    ) -> List[Document]:
        """Process documents into chunks.

        Args:
            documents: Input documents

            Returns:
            Chunked documents
        """
        chunked_docs = []

        for doc in documents:
            chunks = self.splitter.split_text(doc.page_content)

            for i, chunk in enumerate(chunks):
                chunk_doc = Document(
                    page_content=chunk,
                    metadata={
                        **doc.metadata,
                        "chunk_index": i,
                        "original_doc_id": doc.metadata.get("id"),
                    },
                )
                chunked_docs.append(chunk_doc)

        logger.info(f"Processed {len(documents)} documents into {len(chunked_docs)} chunks")
        return chunked_docs

    async def load_from_directory(
        self,
        directory_path: str,
        file_pattern: str = "*.pdf",
    ) -> List[Document]:
        """Load documents from directory.

        Args:
            directory_path: Path to directory
            file_pattern: File pattern to match

            Returns:
            Loaded documents
        """
        try:
            loader = DirectoryLoader(
                directory_path,
                glob=file_pattern,
                loader_cls=PyPDFLoader,
            )
            docs = loader.load()
            logger.info(f"Loaded {len(docs)} documents from {directory_path}")
            return docs
        except Exception as e:
            logger.error(f"Error loading documents: {e}")
            return []


class RAGEngine:
    """Main RAG engine for retrieval-augmented generation."""

    def __init__(
        self,
        vector_store: VectorStore,
        document_processor: Optional[DocumentProcessor] = None,
    ):
        """Initialize RAG engine.

        Args:
            vector_store: Vector store implementation
            document_processor: Document processor
        """
        self.vector_store = vector_store
        self.document_processor = (
            document_processor or DocumentProcessor()
        )
        self.retrieval_history: List[RetrievalMetrics] = []

    async def ingest_documents(
        self,
        documents: List[Document],
    ) -> None:
        """Ingest documents into RAG system.

        Args:
            documents: Documents to ingest
        """
        try:
            processed_docs = await self.document_processor.process_documents(documents)
            await self.vector_store.add_documents(processed_docs)
            logger.info(f"Ingested {len(documents)} documents into RAG system")
        except Exception as e:
            logger.error(f"Error ingesting documents: {e}")
            raise

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        threshold: float = 0.0,
    ) -> RAGContext:
        """Retrieve relevant documents for query.

        Args:
            query: Query string
            k: Number of documents to retrieve
            threshold: Relevance score threshold

            Returns:
            RAG context with retrieved documents
        """
        import time

        start_time = time.time()

        try:
            results = await self.vector_store.search(query, k=k)

            retrieved_docs = []
            relevance_scores = []
            retrieved_chunks = []

            for doc, score in results:
                # Score is typically distance; convert to similarity (1 - distance for normalized)
                similarity = 1.0 - (score / 2.0)  # Approximate conversion

                if similarity >= threshold:
                    retrieved_docs.append(doc)
                    relevance_scores.append(similarity)
                    retrieved_chunks.append(doc.page_content)

            retrieval_time = time.time() - start_time

            metrics = RetrievalMetrics(
                query=query,
                retrieval_time=retrieval_time,
                document_count=len(retrieved_docs),
                relevance_scores=relevance_scores,
                avg_relevance=sum(relevance_scores) / len(relevance_scores)
                if relevance_scores
                else 0.0,
            )

            self.retrieval_history.append(metrics)

            context = RAGContext(
                query=query,
                retrieved_docs=retrieved_docs,
                retrieved_chunks=retrieved_chunks,
                relevance_scores=relevance_scores,
                metrics=metrics,
            )

            logger.info(
                f"Retrieved {len(retrieved_docs)} documents in {retrieval_time:.2f}s "
                f"with avg relevance {metrics.avg_relevance:.2f}"
            )

            return context

        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")
            return RAGContext(query=query)

    async def get_stats(self) -> Dict[str, Any]:
        """Get RAG engine statistics."""
        store_stats = await self.vector_store.get_stats()

        retrieval_stats = {
            "total_retrievals": len(self.retrieval_history),
            "avg_retrieval_time": (
                sum(m.retrieval_time for m in self.retrieval_history)
                / len(self.retrieval_history)
                if self.retrieval_history
                else 0.0
            ),
            "avg_relevance": (
                sum(m.avg_relevance for m in self.retrieval_history)
                / len(self.retrieval_history)
                if self.retrieval_history
                else 0.0
            ),
        }

        return {
            "vector_store": store_stats,
            "retrieval_stats": retrieval_stats,
        }
