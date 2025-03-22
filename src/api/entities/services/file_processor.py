import asyncio
import re

import pdfplumber
import validators
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Union, List, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
from entities.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class FileProcessor:

    def __init__(self, max_workers: int = 4, chunk_size: int = 512):
        self.embedding_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
        self.embedding_model_name = 'paraphrase-MiniLM-L6-v2'
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.max_seq_length = self.embedding_model.get_max_seq_length()
        self.special_tokens_count = 2
        self.effective_max_length = self.max_seq_length - self.special_tokens_count
        self.chunk_size = min(chunk_size, self.effective_max_length * 4)
        logging_utility.info("Initialized optimized FileProcessor")


    def validate_file(self, file_path: Path):
        """Pre-process validation checks"""
        max_size = 100 * 1024 * 1024  # 100MB
        if file_path.stat().st_size > max_size:
            raise ValueError(f"File {file_path} exceeds size limit of {max_size // (1024 * 1024)}MB")
        if not file_path.exists():
            raise FileNotFoundError(f"File {file_path} not found")

    def _detect_file_type(self, file_path: Path) -> str:
        """Enhanced file type detection"""
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        elif suffix in {".txt", ".md", ".rst"}:
            return "text"
        else:
            return "unknown"

    async def process_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Async file processing pipeline"""
        file_path = Path(file_path)
        self.validate_file(file_path)

        file_type = self._detect_file_type(file_path)

        # Handle both PDF and text files
        if file_type == "pdf":
            return await self._process_pdf(file_path)
        elif file_type == "text":
            return await self._process_text(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

    async def _process_pdf(self, file_path: Path) -> Dict[str, Any]:
        """Process PDF with line number tracking"""
        try:
            page_chunks, doc_metadata = await self._extract_text(file_path)
            all_chunks = []
            chunk_line_data = []

            for page_text, page_num, line_nums in page_chunks:
                page_lines = page_text.split('\n')
                current_chunk = []
                current_line_nums = []
                current_length = 0

                for line, line_num in zip(page_lines, line_nums):
                    line_len = len(line) + 1  # Account for newline

                    if current_length + line_len <= self.chunk_size:
                        current_chunk.append(line)
                        current_line_nums.append(line_num)
                        current_length += line_len
                    else:
                        if current_chunk:
                            # Save existing chunk
                            all_chunks.append('\n'.join(current_chunk))
                            chunk_line_data.append({
                                'page': page_num,
                                'lines': current_line_nums,
                                'line_count': len(current_line_nums)
                            })
                            current_chunk = []
                            current_line_nums = []
                            current_length = 0

                        # Handle oversized line
                        chunks = self._split_oversized_line(line)
                        for chunk in chunks:
                            all_chunks.append(chunk)
                            chunk_line_data.append({
                                'page': page_num,
                                'lines': [line_num],
                                'line_count': 1
                            })

                if current_chunk:
                    all_chunks.append('\n'.join(current_chunk))
                    chunk_line_data.append({
                        'page': page_num,
                        'lines': current_line_nums,
                        'line_count': len(current_line_nums)
                    })

            vectors = await asyncio.gather(*[
                self._encode_chunk_async(chunk)
                for chunk in all_chunks
            ])

            return {
                "content": "\n".join(all_chunks),
                "metadata": {
                    **doc_metadata,
                    "source": str(file_path),
                    "chunks": len(all_chunks),
                    "type": "pdf"
                },
                "vectors": [v.tolist() for v in vectors],
                "chunks": all_chunks,
                "line_data": chunk_line_data
            }

        except Exception as e:
            logging_utility.error(f"PDF processing failed [{file_path.name}]: {str(e)}")
            raise

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
                "chunks": chunks
            }
        except Exception as e:
            logging_utility.error(f"Processing failed: {str(e)}")
            raise

    async def _extract_text(self, file_path: Path) -> Union[str, Tuple[str, dict, list]]:
        """Unified text extraction"""
        loop = asyncio.get_event_loop()

        if file_path.suffix.lower() == ".pdf":
            return await loop.run_in_executor(
                self._executor,
                self._extract_pdf_text,
                file_path
            )
        else:
            text = await loop.run_in_executor(
                self._executor,
                self._read_text_file,
                file_path
            )
            return text, {}, []

    def _extract_pdf_text(self, file_path: Path) -> Tuple[List[Tuple[str, int, List[int]]], dict]:
        """PDF extraction with line number tracking"""
        page_chunks = []
        metadata = {}
        with pdfplumber.open(file_path) as pdf:
            metadata.update({
                'author': pdf.metadata.get('Author', 'unknown_author'),
                'title': pdf.metadata.get('Title', Path(file_path).stem),
                'publication_date': pdf.metadata.get('CreationDate'),
                'page_count': len(pdf.pages),
                'type': 'pdf'
            })

            for page_num, page in enumerate(pdf.pages, 1):
                lines = page.extract_text_lines()
                text_buffer = []
                line_numbers = []

                for line in sorted(lines, key=lambda l: l['top']):
                    line_text = line['text'].strip()
                    if line_text:
                        text_buffer.append(line_text)
                        line_numbers.append(line['line_number'])

                if text_buffer:
                    page_chunks.append(('\n'.join(text_buffer), page_num, line_numbers))

                page.flush_cache()

        return page_chunks, metadata


    def _read_text_file(self, file_path: Path) -> str:
        """Read text files with encoding fallback"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()

    async def _encode_chunk_async(self, chunk: str) -> np.ndarray:
        """Safe embedding generation with validation"""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor,
            lambda: self.embedding_model.encode(
                [chunk],
                convert_to_numpy=True,
                truncate='model_max_length',
                normalize_embeddings=True,
                show_progress_bar=False
            )[0]
        )

    def _chunk_text(self, text: str) -> List[str]:
        """Token-aware text chunking with size validation"""
        text = text.strip()
        if not text:
            return []

        # Initial semantic chunking
        base_chunks = self._initial_semantic_chunking(text)

        # Token-based size validation and splitting
        final_chunks = []
        for chunk in base_chunks:
            tokens = self.embedding_model.tokenizer.tokenize(chunk)
            if len(tokens) <= self.max_seq_length:
                final_chunks.append(chunk)
            else:
                final_chunks.extend(self._split_oversized_chunk(chunk, tokens))

        return [chunk for chunk in final_chunks if chunk.strip()]

    def _initial_semantic_chunking(self, text: str) -> List[str]:
        """Create initial chunks preserving sentence boundaries"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence) + 1  # Account for space separator

            if current_length + sentence_len <= self.chunk_size:
                current_chunk.append(sentence)
                current_length += sentence_len
            else:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Handle sentence longer than chunk size
                while len(sentence) > self.chunk_size:
                    chunk_part = sentence[:self.chunk_size]
                    chunks.append(chunk_part)
                    sentence = sentence[self.chunk_size:].lstrip()
                    current_length = len(sentence)

                if sentence:
                    current_chunk.append(sentence)
                    current_length += len(sentence)

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks

    def _split_oversized_chunk(self, chunk: str, tokens: List[str] = None) -> List[str]:
        """Split chunks with special token allowance"""
        if not tokens:
            tokens = self.embedding_model.tokenizer.tokenize(chunk)

        chunks = []
        for i in range(0, len(tokens), self.effective_max_length):
            chunk_tokens = tokens[i:i + self.effective_max_length]
            chunk_text = self.embedding_model.tokenizer.convert_tokens_to_string(chunk_tokens)
            chunks.append(chunk_text)

        return chunks

    def _generate_chunk_metadata(self, processed_data: dict, chunk_idx: int,
                                 doc_metadata: dict) -> dict:
        """Generate metadata with page numbers"""
        chunk_text = processed_data['chunks'][chunk_idx]
        page_number = processed_data['page_numbers'][chunk_idx]

        # Token calculation
        tokens = self.embedding_model.tokenizer.tokenize(chunk_text)
        token_count = len(tokens) if tokens else 0

        return {
            # Core fields
            "source": str(Path(doc_metadata['source'])),
            "document_type": doc_metadata.get('type', 'pdf'),
            "retrieved_date": datetime.now().isoformat(),
            "page_number": page_number,

            # Auto-generated
            "chunk_id": f"{Path(doc_metadata['source']).stem}_chunk{chunk_idx:04d}",
            "token_count": token_count,

            # Document metadata
            "author": doc_metadata.get('author', 'unknown_author'),
            "publication_date": doc_metadata.get('publication_date'),
            "title": doc_metadata.get('title', ''),

            # Technical info
            "embedding_model": self.embedding_model_name
        }

    def _validate_metadata(self, metadata: dict):
        """Validate metadata structure"""
        if not metadata.get('source') and not metadata.get('url'):
            raise ValueError("Metadata must contain either 'source' or 'url'")

        if metadata.get('url') and not validators.url(metadata['url']):
            raise ValueError(f"Invalid URL format: {metadata['url']}")

        if metadata.get('url') and not metadata.get('document_type'):
            metadata['document_type'] = 'web_content'
            logging_utility.info("Auto-set document_type to 'web_content' for URL source")

    def _extract_domain(self, url: str) -> Union[str, None]:
        """Extract domain from URL"""
        if not url:
            return None
        try:
            return url.split('//')[-1].split('/')[0].lower()
        except:
            return None

    def process_and_store(self,
                          file_path: Union[str, Path],
                          destination_store: str,
                          vector_service,
                          user_metadata: dict = None,
                          source_url: str = None) -> dict:
        """Process documents with metadata support"""
        # Convert to Path immediately (CRITICAL FIX)
        file_path = Path(file_path)

        metadata = user_metadata.copy() if user_metadata else {}
        if source_url:
            metadata['url'] = source_url

        try:
            processed = asyncio.run(
                self._async_process_and_store(
                    file_path,  # Now a Path object
                    destination_store,
                    vector_service,
                    metadata
                )
            )
            return {
                "store_name": destination_store,
                "status": "success",
                "chunks_processed": processed["chunks_processed"],
                "metadata_summary": processed["metadata_summary"]
            }
        except Exception as e:
            logging_utility.error(f"Processing failed: {str(e)}")
            raise

    async def _async_process_and_store(self,
                                      file_path: Path,
                                      destination_store: str,
                                      vector_service,
                                      doc_metadata: dict):
        """Process and store with page tracking"""
        processed = await self.process_file(file_path)
        chunk_metadata = [
            self._generate_chunk_metadata(processed, idx, doc_metadata)
            for idx in range(processed["metadata"]["chunks"])
        ]

        vector_service.add_to_store(
            store_name=destination_store,
            texts=processed["chunks"],
            vectors=processed["vectors"],
            metadata=chunk_metadata
        )

        return {
            "store_name": destination_store,
            "chunks_processed": processed["metadata"]["chunks"],
            "metadata_summary": doc_metadata
        }