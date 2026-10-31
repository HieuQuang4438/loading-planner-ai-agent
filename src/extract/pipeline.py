"""Documents of a lot to the lot (docs/product/brief.md §2.1): one model call per document, in parallel, then the
fixed merge. A document that fails is reported with its error and the others still count."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from src.extract.documents import Upload
from src.extract.merge import Doc, merge
from src.extract.readings import DocumentReading
from src.llm.client import LLM, LLMError, Part
from src.lot.schema import Lot

PROMPT = "extract_document"
WORKERS = 4


@dataclass
class Extraction:
    lot: Lot
    docs: list[Doc]
    failed: dict[str, str] = field(default_factory=dict)  # file name -> why it could not be read


def read_document(llm: LLM, upload: Upload) -> DocumentReading:
    part = Part(text=f"Tệp: {upload.name}\n\n{upload.text}") if upload.text is not None else Part(data=upload.data, mime=upload.mime)
    note = Part(text=f"Tên tệp: {upload.name}")
    return llm.generate(PROMPT, [note, part], DocumentReading)


def extract(llm: LLM, name: str, uploads: list[Upload]) -> Extraction:
    docs: list[Doc] = []
    failed: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [(u, pool.submit(read_document, llm, u)) for u in uploads]
        for upload, future in futures:  # in upload order, so lines keep the documents' order
            try:
                docs.append(Doc(upload.name, future.result()))
            except LLMError as exc:
                failed[upload.name] = str(exc)
    return Extraction(merge(name, docs), docs, failed)
