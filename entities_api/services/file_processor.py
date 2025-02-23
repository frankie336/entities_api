import asyncio
import pdfplumber
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, Union, List
import numpy as np
from sentence_transformers import SentenceTransformer
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class FileProcessor:
    def __init__(self, max_workers: int = 4, chunk_size: int = 512):
        self.embedding_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.chunk_size = chunk_size
        logging_utility.info("Initialized optimized FileProcessor")

    def validate_file(self, file_path: Path):
        """Pre-process validation checks"""
        max_size = 100 * 1024 * 1024  # 100MB
        if file_path.stat().st_size > max_size:
            raise ValueError(f"File {file_path} exceeds size limit of {max_size // (1024 * 1024)}MB")
        if not file_path.exists():
            raise FileNotFoundError(f"File {file_path} not found")

    def _detect_file_type(self, file_path: Path) -> str:
        """Detect file type based on extension"""
        if file_path.suffix.lower() == ".pdf":
            return "pdf"
        elif file_path.suffix.lower() in {".txt", ".md", ".rst"}:
            return "text"
        else:
            return "unknown"

    async def process_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Async file processing pipeline"""
        file_path = Path(file_path)
        self.validate_file(file_path)

        file_type = self._detect_file_type(file_path)
        if file_type != "text":
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        return await self._process_text(file_path)

    async def _process_text(self, file_path: Path) -> Dict[str, Any]:
        """Process text with proper async handling"""
        try:
            text = await self._extract_text(file_path)
            chunks = self._chunk_text(text)

            vectors = await asyncio.gather(*[
                self._encode_chunk_async(chunk)
                for chunk in chunks
            ])

            return {
                "content": text,
                "metadata": {
                    "type": "text",
                    "source": str(file_path),
                    "chunks": len(chunks)
                },
                "vectors": [v.tolist() for v in vectors],
                "chunks": chunks  # Add this line to store individual chunks
            }


        except Exception as e:
            logging_utility.error(f"Processing failed: {str(e)}")
            raise

    async def _extract_text(self, file_path: Path) -> str:
        """Async text extraction"""
        loop = asyncio.get_event_loop()
        if file_path.suffix.lower() == ".pdf":
            return await loop.run_in_executor(
                self._executor,
                self._extract_pdf_text,
                file_path
            )
        else:
            return await loop.run_in_executor(
                self._executor,
                self._read_text_file,
                file_path
            )

    def _extract_pdf_text(self, file_path: Path) -> str:
        """PDF extraction with memory optimization"""
        buffer = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    buffer.append(text)
                page.flush_cache()
        return "\n".join(buffer)

    def _read_text_file(self, file_path: Path) -> str:
        """Read text files with encoding fallback"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()

    async def _encode_chunk_async(self, chunk: str) -> np.ndarray:
        """Async wrapper for embedding generation"""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor,
            lambda: self.embedding_model.encode([chunk], convert_to_numpy=True)[0]
        )

    def _chunk_text(self, text: str) -> List[str]:
        """Semantic-aware text chunking"""
        sentences = text.split('. ')
        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if current_length + len(sentence) > self.chunk_size:
                chunks.append(". ".join(current_chunk) + ".")
                current_chunk = []
                current_length = 0

            current_chunk.append(sentence)
            current_length += len(sentence)

        if current_chunk:
            chunks.append(". ".join(current_chunk).strip())

        return chunks or [text]

    # In FileProcessor class
    def process_and_store(self, file_path: Union[str, Path], destination_store: str, vector_service) -> dict:
        """Synchronous entry point"""
        try:
            processed = asyncio.run(self._async_process_and_store(file_path, destination_store, vector_service))
            return {
                "store_name": destination_store,
                "status": "success",
                "chunks_processed": processed["chunks_processed"]  # Changed key
            }
        except Exception as e:
            logging_utility.error(f"Processing failed: {str(e)}")
            raise

    async def _async_process_and_store(self, file_path: Path, destination_store: str, vector_service):
        """Internal async processing"""
        processed = await self.process_file(file_path)

        # Create metadata for each chunk
        chunk_metadata = [{
            "source": processed["metadata"]["source"],
            "chunk_index": idx,
            "total_chunks": processed["metadata"]["chunks"]
        } for idx in range(processed["metadata"]["chunks"])]

        vector_service.add_to_store(
            store_name=destination_store,
            texts=processed["chunks"],
            vectors=processed["vectors"],
            metadata=chunk_metadata
        )

        # Return the count instead of length of an integer
        return {
            "store_name": destination_store,
            "chunks_processed": processed["metadata"]["chunks"]  # Use metadata count
        }