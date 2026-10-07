"""
ECHO - Document Processing Module

Pipeline:
    PDF
      ↓
    PyMuPDF Text Extraction
      ↓
    OCR Fallback for Scanned/Image PDFs
      ↓
    Text Cleaning
      ↓
    Text Chunking
      ↓
    spaCy Named Entity Recognition
      ↓
    Structured JSON

Supported entities:
    PERSON
    DATE
    TIME
    ORG
    GPE
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import fitz
import pytesseract
import spacy
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_CHUNK_SIZE = 500

SUPPORTED_ENTITY_TYPES = {
    "PERSON",
    "DATE",
    "TIME",
    "ORG",
    "GPE",
}

# Common Windows Tesseract installation paths
TESSERACT_PATHS = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


# ============================================================
# TESSERACT CONFIGURATION
# ============================================================

def configure_tesseract() -> bool:
    """
    Configure Tesseract OCR executable.

    Returns:
        True if Tesseract is available, otherwise False.
    """

    # First try PATH
    try:
        version = pytesseract.get_tesseract_version()

        if version:
            return True

    except Exception:
        pass

    # Try common Windows installation paths
    for path in TESSERACT_PATHS:

        if path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(path)
            return True

    return False


# ============================================================
# OCR
# ============================================================

def extract_text_with_ocr(
    page: fitz.Page,
    page_number: int,
) -> str:
    """
    Render a PDF page as an image and extract text using OCR.

    Args:
        page: PyMuPDF page object.
        page_number: Current page number.

    Returns:
        OCR extracted text.
    """

    if not configure_tesseract():
        raise RuntimeError(
            "Tesseract OCR was not found.\n"
            "Install Tesseract OCR on Windows and try again."
        )

    try:
        # Render page at 300 DPI for better OCR accuracy
        matrix = fitz.Matrix(300 / 72, 300 / 72)

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        # Convert Pixmap to PNG bytes
        image_bytes = pixmap.tobytes("png")

        # Open image using Pillow
        image = Image.open(
            __import__("io").BytesIO(image_bytes)
        )

        # OCR
        text = pytesseract.image_to_string(
            image,
            config="--psm 6",
        )

        return text.strip()

    except Exception as exc:
        raise RuntimeError(
            f"OCR failed on page {page_number}: {exc}"
        ) from exc


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_text_from_pdf(
    pdf_path: str | Path,
) -> str:
    """
    Extract text from a PDF.

    Strategy:
        1. Try normal PyMuPDF text extraction.
        2. If a page contains no selectable text,
           automatically use OCR on that page.

    Args:
        pdf_path: Path to PDF.

    Returns:
        Complete extracted text.
    """

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(
            f"PDF file not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Provided path is not a file: {path}"
        )

    if path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a PDF file, received: {path.suffix}"
        )

    text_parts: list[str] = []

    try:

        with fitz.open(path) as document:

            if document.page_count == 0:
                raise ValueError("PDF contains no pages.")

            for page_number, page in enumerate(
                document,
                start=1,
            ):

                # ------------------------------------------------
                # STEP 1: Normal PDF text extraction
                # ------------------------------------------------

                page_text = page.get_text("text").strip()

                if page_text:
                    print(
                        f"  Page {page_number}: "
                        f"Text extracted"
                    )

                    text_parts.append(page_text)

                    continue

                # ------------------------------------------------
                # STEP 2: OCR fallback
                # ------------------------------------------------

                print(
                    f"  Page {page_number}: "
                    f"No text layer -> OCR"
                )

                try:

                    ocr_text = extract_text_with_ocr(
                        page,
                        page_number,
                    )

                    if ocr_text:
                        text_parts.append(ocr_text)

                        print(
                            f"  Page {page_number}: "
                            f"OCR successful"
                        )

                    else:
                        print(
                            f"  Page {page_number}: "
                            f"OCR returned no text"
                        )

                except RuntimeError as exc:

                    print(
                        f"  Page {page_number}: "
                        f"OCR failed - {exc}",
                        file=sys.stderr,
                    )

    except fitz.FileDataError as exc:

        raise RuntimeError(
            f"Invalid or corrupted PDF: {exc}"
        ) from exc

    except Exception as exc:

        if isinstance(
            exc,
            (FileNotFoundError, ValueError, RuntimeError),
        ):
            raise

        raise RuntimeError(
            f"Unable to process PDF '{path}': {exc}"
        ) from exc

    return "\n".join(text_parts)


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text: str) -> str:
    """
    Clean extracted PDF/OCR text.

    Operations:
        - Normalize whitespace
        - Remove unwanted symbols
        - Preserve useful punctuation
        - Remove leading/trailing spaces
    """

    if not text:
        return ""

    # Normalize whitespace
    cleaned = re.sub(
        r"\s+",
        " ",
        text,
    )

    # Remove unwanted special characters
    cleaned = re.sub(
        r"[^\w\s.,!?;:()@/\-]",
        "",
        cleaned,
        flags=re.UNICODE,
    )

    # Normalize spaces again
    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    )

    return cleaned.strip()


# ============================================================
# TEXT CHUNKING
# ============================================================

def split_into_chunks(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[str]:
    """
    Split text into word-based chunks.

    Args:
        text: Cleaned text.
        chunk_size: Maximum words per chunk.

    Returns:
        List of chunks.
    """

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be greater than zero."
        )

    if not text.strip():
        return []

    words = text.split()

    return [
        " ".join(
            words[index:index + chunk_size]
        )
        for index in range(
            0,
            len(words),
            chunk_size,
        )
    ]


# ============================================================
# SPACY MODEL
# ============================================================

def load_nlp_model(
    model_name: str = "en_core_web_sm",
):
    """
    Load spaCy NLP model.
    """

    try:
        return spacy.load(model_name)

    except OSError as exc:

        raise RuntimeError(
            f"spaCy model '{model_name}' is not installed.\n\n"
            f"Install it using:\n"
            f"python -m spacy download {model_name}"
        ) from exc


# ============================================================
# ENTITY EXTRACTION
# ============================================================

def extract_entities(
    text: str,
    nlp,
) -> list[dict[str, str]]:
    """
    Extract supported named entities using spaCy.
    """

    if not text.strip():
        return []

    doc = nlp(text)

    entities: list[dict[str, str]] = []

    for entity in doc.ents:

        if entity.label_ not in SUPPORTED_ENTITY_TYPES:
            continue

        entity_text = entity.text.strip()

        if not entity_text:
            continue

        entities.append(
            {
                "text": entity_text,
                "type": entity.label_,
            }
        )

    return entities


# ============================================================
# UNIQUE VALUES
# ============================================================

def unique_values(
    values: list[str],
) -> list[str]:
    """
    Remove duplicates while preserving order.
    """

    return list(
        dict.fromkeys(
            value.strip()
            for value in values
            if value and value.strip()
        )
    )


# ============================================================
# STRUCTURED INFORMATION
# ============================================================

def create_structured_data(
    entities: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Organize entities into structured categories.
    """

    people: list[str] = []
    dates: list[str] = []
    organizations: list[str] = []
    locations: list[str] = []

    for entity in entities:

        entity_text = entity["text"]
        entity_type = entity["type"]

        if entity_type == "PERSON":
            people.append(entity_text)

        elif entity_type in {
            "DATE",
            "TIME",
        }:
            dates.append(entity_text)

        elif entity_type == "ORG":
            organizations.append(entity_text)

        elif entity_type == "GPE":
            locations.append(entity_text)

    return {
        "people": unique_values(people),
        "dates": unique_values(dates),
        "organizations": unique_values(organizations),
        "locations": unique_values(locations),
        "entities": entities,
    }


# ============================================================
# COMPLETE PIPELINE
# ============================================================

def process_document(
    pdf_path: str | Path,
    nlp,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, Any]:
    """
    Run the complete ECHO document processing pipeline.
    """

    pdf_path = Path(pdf_path)

    print("\nExtracting document text...")

    raw_text = extract_text_from_pdf(
        pdf_path
    )

    if not raw_text.strip():

        raise RuntimeError(
            "No text could be extracted from the PDF.\n"
            "The document may contain unsupported images "
            "or extremely low-quality scans."
        )

    print("\nCleaning text...")

    cleaned_text = clean_text(
        raw_text
    )

    print("Creating chunks...")

    chunks = split_into_chunks(
        cleaned_text,
        chunk_size,
    )

    print("Running NLP entity extraction...")

    entities = extract_entities(
        cleaned_text,
        nlp,
    )

    structured_data = create_structured_data(
        entities
    )

    return {
        "document": {
            "filename": pdf_path.name,
            "path": str(
                pdf_path.resolve()
            ),
        },
        "raw_text": raw_text,
        "cleaned_text": cleaned_text,
        "chunks": chunks,
        "chunk_count": len(chunks),
        "structured_data": structured_data,
    }


# ============================================================
# SAVE JSON
# ============================================================

def save_json(
    data: dict[str, Any],
    output_path: str | Path,
) -> None:
    """
    Save processed data to JSON.
    """

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False,
        )


# ============================================================
# COMMAND LINE ARGUMENTS
# ============================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "ECHO - Offline Document Processing Pipeline"
        )
    )

    parser.add_argument(
        "pdf",
        help="Path to the PDF file",
    )

    parser.add_argument(
        "-o",
        "--output",
        default="structured_data.json",
        help="Output JSON path",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Maximum words per chunk",
    )

    parser.add_argument(
        "--model",
        default="en_core_web_sm",
        help="spaCy model",
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    args = parse_arguments()

    try:

        print("=" * 50)
        print("ECHO - Document Processing")
        print("=" * 50)

        print(f"PDF        : {args.pdf}")
        print(f"Model      : {args.model}")
        print(f"Chunk size : {args.chunk_size}")

        # ----------------------------------------------------
        # 1. Load NLP model
        # ----------------------------------------------------

        print("\n[1/5] Loading NLP model...")

        nlp = load_nlp_model(
            args.model
        )

        # ----------------------------------------------------
        # 2. Process PDF
        # ----------------------------------------------------

        print("\n[2/5] Processing PDF...")

        result = process_document(
            pdf_path=args.pdf,
            nlp=nlp,
            chunk_size=args.chunk_size,
        )

        # ----------------------------------------------------
        # 3. Structured information
        # ----------------------------------------------------

        print(
            "\n[3/5] Extracting structured information..."
        )

        # Already completed inside process_document()

        # ----------------------------------------------------
        # 4. Save JSON
        # ----------------------------------------------------

        print("\n[4/5] Saving JSON...")

        save_json(
            result,
            args.output,
        )

        # ----------------------------------------------------
        # 5. Completion
        # ----------------------------------------------------

        print("\n[5/5] Processing completed.")

        print("\n" + "-" * 50)

        print(
            f"Document : "
            f"{result['document']['filename']}"
        )

        print(
            f"Characters : "
            f"{len(result['cleaned_text'])}"
        )

        print(
            f"Chunks   : "
            f"{result['chunk_count']}"
        )

        print(
            f"Entities : "
            f"{len(result['structured_data']['entities'])}"
        )

        print(
            f"Output   : "
            f"{Path(args.output).resolve()}"
        )

        print("-" * 50)

        return 0

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as exc:

        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    except KeyboardInterrupt:

        print(
            "\nProcessing cancelled by user.",
            file=sys.stderr,
        )

        return 130

    except Exception as exc:

        print(
            f"\nUNEXPECTED ERROR: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )