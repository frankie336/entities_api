import pdfplumber
from pathlib import Path
from typing import Dict, Any, Union
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class FileProcessor:
    def __init__(self):
        logging_utility.info("Initialized Text File Processor")

    def process_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Main file processing entry point for text files"""
        file_path = Path(file_path)
        file_type = self._detect_file_type(file_path)

        if file_type != "text":
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        return self._process_text(file_path)

    def _detect_file_type(self, file_path: Path) -> str:
        """Detect text file type from extension"""
        ext = file_path.suffix.lower()[1:]
        if ext in ["pdf", "txt", "md"]:
            return "text"
        raise ValueError(f"Unsupported file type: {ext}")

    def _process_text(self, file_path: Path) -> Dict[str, Any]:
        """Process text-based files including PDF"""
        try:
            if file_path.suffix.lower() == ".pdf":
                with pdfplumber.open(file_path) as pdf:
                    text = "\n".join(page.extract_text() for page in pdf.pages)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()

            return {
                "content": text,
                "metadata": {
                    "type": "text",
                    "source": str(file_path),
                    "length": len(text)
                }
            }

        except Exception as e:
            logging_utility.error(f"Text processing failed: {str(e)}")
            raise RuntimeError(f"Text processing error: {str(e)}")

    def process_and_store(self, file_path: Union[str, Path], vector_service, embedding_model):
        """End-to-end processing pipeline for text files"""
        try:
            processed = self.process_file(file_path)
            store_info = vector_service.create_store_for_file_type("text")

            vector_service.add_to_store(
                store_name=store_info["name"],
                texts=[processed["content"]],
                vectors=[embedding_model.encode(processed["content"])],
                metadata=[processed["metadata"]]
            )
            return store_info

        except Exception as e:
            logging_utility.error(f"Processing pipeline failed: {str(e)}")
            raise