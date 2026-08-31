from pathlib import Path

# the sample boarding pass shipped with the repository
SAMPLE_PDF_PATH = Path(__file__).resolve().parent.parent / "test_data" / "boarding_pass.pdf"


def sample_pdf_bytes() -> bytes:
    return SAMPLE_PDF_PATH.read_bytes()
