"""
generate_samples.py — One-off script to produce sample_data PDF files.

Creates:
  sample_data/rate_confirmation.pdf   — text-layer PDF of the sample document
  sample_data/image_only.pdf          — blank page (simulates scanned PDF)

Run from the freight_parser/ directory:
    python generate_samples.py
"""

from pathlib import Path

from fpdf import FPDF

SAMPLE_DATA = Path("sample_data")

# ---------------------------------------------------------------------------
# Full-text rate confirmation PDF
# ---------------------------------------------------------------------------

CONTENT = """\
RATE CONFIRMATION

Carrier:        Apex Logistics Solutions LLC
Ref #:          LD-994821

SHIPMENT DETAILS

Pickup Location:
  Distribution Center 4
  Dallas, TX 75201

Delivery Location:
  Warehouse B
  Atlanta, GA 30303

Total Weight:   46,800 lbs

RATE BREAKDOWN

Linehaul Rate:      $2,200.00
Fuel Surcharge:     $  350.00
Total Pay:          $2,800.00

TERMS & CONDITIONS

Payment terms: Net 30 days upon receipt of signed proof of delivery (POD)
and invoice. Carrier agrees to comply with all applicable federal, state,
and local regulations. Any detention charges must be pre-approved by the
broker.

Authorized Signature: _______________________
Date: _______________
"""


def make_text_pdf(path: Path, content: str) -> None:
    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, content)
    pdf.output(str(path))
    print(f"Created: {path}")


def make_blank_pdf(path: Path) -> None:
    """Blank page — no text layer — simulates a scanned image-only PDF."""
    pdf = FPDF()
    pdf.add_page()
    # No text added intentionally
    pdf.output(str(path))
    print(f"Created: {path}")


if __name__ == "__main__":
    SAMPLE_DATA.mkdir(exist_ok=True)
    make_text_pdf(SAMPLE_DATA / "rate_confirmation.pdf", CONTENT)
    make_blank_pdf(SAMPLE_DATA / "image_only.pdf")
    print("Done.")
