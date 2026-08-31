from pathlib import Path

TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "test_data"

# single boarding pass, one leg, one page
SAMPLE_PDF_PATH = TEST_DATA_DIR / "boarding_pass.pdf"

# outbound and return, two pages, one single-leg boarding pass on each - a return journey is a
# separate check-in, so it is a second boarding pass rather than a second leg of the first one
RETURN_PDF_PATH = TEST_DATA_DIR / "Boarding_Pass_and_return.pdf"

# a valid PDF that simply has no barcode on it
NO_BARCODE_PDF_PATH = TEST_DATA_DIR / "sample_not_boarding_pass.pdf"


def sample_pdf_bytes() -> bytes:
    return SAMPLE_PDF_PATH.read_bytes()


def return_pdf_bytes() -> bytes:
    return RETURN_PDF_PATH.read_bytes()


def no_barcode_pdf_bytes() -> bytes:
    return NO_BARCODE_PDF_PATH.read_bytes()
