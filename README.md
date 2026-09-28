# Freight Parser

A lightweight Python application for extracting and validating structured data from freight documents and rate confirmations using Groq LLMs.

## Project Structure

```
freight_parser/
├── src/freight_parser/
│   ├── agent.py       # Orchestrates extraction and validation
│   ├── cli.py         # Command-line interface
│   ├── config.py      # Environment and application configuration
│   ├── errors.py      # Custom exception hierarchy
│   ├── extractor.py   # LLM interaction using Instructor
│   ├── ingest.py      # Document loading and normalization
│   ├── schemas.py     # Pydantic data models
│   └── validator.py   # Deterministic business rule validation
├── tests/             # Pytest test suite
├── sample_data/       # Sample PDF and TXT documents
└── sample_output/     # Captured CLI output
```

## Supported Inputs

- **Plain Text (`.txt`, `.md`)**: Read as UTF-8.
- **PDFs (`.pdf`)**: Must contain a text layer. The application uses `pdfplumber` to extract text.
- **Standard Input (`stdin`)**: Read plain text directly via pipelines.

*Note: Scanned or image-only PDFs are currently unsupported. If a PDF contains fewer than 50 text characters, it will be rejected as image-only.*

## Setup

Requires **Python 3.10+**.

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```
3. Configure the environment:
   ```bash
   cp .env.example .env
   ```
4. Edit `.env` and set your API key and preferred model (e.g., `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`):
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

## Usage

The application can be run either via the modern Web UI or the Command-Line Interface (CLI).

### 1. Web Interface (Recommended)

Start the FastAPI backend server, which also serves the web frontend:

```bash
python -m uvicorn freight_parser.api:app --host 0.0.0.0 --port 8000
```

Then, open your web browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

You can drag and drop your PDF or TXT files directly into the browser to see the extraction results in real-time.

### 2. Command-Line Interface (CLI)

Run the CLI module, passing the path to the document:

**Extract from PDF:**
```bash
python -m freight_parser.cli --file sample_data/rate_confirmation.pdf
```

**Extract from TXT and save JSON:**
```bash
python -m freight_parser.cli --file sample_data/rate_confirmation.txt --output result.json
```

**Extract from stdin:**
```bash
cat sample_data/rate_confirmation.txt | python -m freight_parser.cli
```

### 3. Exit Codes (CLI)
- `0`: **APPROVED** - Document parsed and passed all validation rules.
- `1`: **FLAGGED_FOR_HUMAN_REVIEW** - Document had validation warnings/errors, or extraction failed.
- `2`: **ERROR** - Configuration, file I/O, or unsupported format error.

### 4. Running Tests
Execute the pytest suite (no LLM calls are made during tests):
```bash
pytest tests/ -v
```

## Sample Output

Running against a flawed document (`sample_data/rate_confirmation.pdf`):

```text
══════════════════════════════════════════════════════
  FREIGHT DOCUMENT VALIDATION REPORT
══════════════════════════════════════════════════════
  Carrier      : Apex Logistics Solutions LLC
  Load #       : LD-994821
──────────────────────────────────────────────────────
  Origin       : Distribution Center 4, Dallas, TX, 75201
  Destination  : Warehouse B, Atlanta, GA, 30303
──────────────────────────────────────────────────────
  Weight       : 46,800 lbs
  Linehaul     : $2,200.00
  Fuel Surcharge: $350.00
  Total Pay    : $2,800.00
──────────────────────────────────────────────────────
  ISSUES FOUND (2):
    [ERROR] RATE_MISMATCH
      2200.00 + 350.00 = 2550.00, but total_pay is 2800.00 (difference 250.00).  [fields: total_linehaul_rate, fuel_surcharge, total_pay]
    [WARNING] OVERWEIGHT_LOAD
      Weight 46,800 lbs exceeds the 45,000 lb limit by 1,800 lbs.  [fields: weight_lbs]
──────────────────────────────────────────────────────
  OUTCOME: ⛔  FLAGGED FOR HUMAN REVIEW
══════════════════════════════════════════════════════

Full decision JSON:
{
  "status": "FLAGGED_FOR_HUMAN_REVIEW",
  "summary": "Flagged: 1 error, 1 warning. [ERROR] RATE_MISMATCH: 2200.00 + 350.00 = 2550.00, but total_pay is 2800.00 (difference 250.00). [WARNING] OVERWEIGHT_LOAD: Weight 46,800 lbs exceeds the 45,000 lb limit by 1,800 lbs.",
  "data": {
    "carrier_name": "Apex Logistics Solutions LLC",
    "load_number": "LD-994821",
    "pickup_location": {
      "facility_name": "Distribution Center 4",
      "city": "Dallas",
      "state": "TX",
      "zip_code": "75201"
    },
    "delivery_location": {
      "facility_name": "Warehouse B",
      "city": "Atlanta",
      "state": "GA",
      "zip_code": "30303"
    },
    "total_linehaul_rate": 2200.0,
    "fuel_surcharge": 350.0,
    "total_pay": 2800.0,
    "weight_lbs": 46800
  },
  "issues": [
    {
      "code": "RATE_MISMATCH",
      "severity": "ERROR",
      "message": "2200.00 + 350.00 = 2550.00, but total_pay is 2800.00 (difference 250.00).",
      "fields": [
        "total_linehaul_rate",
        "fuel_surcharge",
        "total_pay"
      ]
    },
    {
      "code": "OVERWEIGHT_LOAD",
      "severity": "WARNING",
      "message": "Weight 46,800 lbs exceeds the 45,000 lb limit by 1,800 lbs.",
      "fields": [
        "weight_lbs"
      ]
    }
  ]
}
```

## Architecture Note

Strict JSON extraction is guaranteed by supplying the Pydantic schema as a tool definition to the LLM via `instructor`. The model is constrained to generate conforming JSON structures rather than relying on probabilistic text formatting. The pipeline enforces a temperature of 0 for reproducibility and explicitly instructs the model to *never guess* or *recompute* missing values. If extraction produces invalid types (e.g., a string instead of a float after Pydantic coercion attempts), a validation error is fed back to the model in a retry loop. Once valid data is extracted, the application intentionally delegates deterministic business logic (like arithmetic rate checks) to pure Python code, isolating probabilistic language tasks from strict rules. This surfaces gaps as explicit `INCOMPLETE_DATA` validation issues.

To scale this to 100,000 PDFs/day, the architecture would shift to an asynchronous, event-driven model using S3 and a message queue (SQS, Kafka, or Celery) processing stateless, auto-scaling worker nodes. The `ingest.py` check for text-density would act as a router: text-heavy PDFs route to the cheap, fast LLM extraction path, while image-heavy or scanned PDFs route to OCR/layout services (like AWS Textract or Document AI) or multimodal vision models. Batch APIs and prompt caching would be heavily utilized to manage token costs.

Robust operations at scale demand exponential backoff for rate limits, a dead-letter queue for persistent failures, and idempotency keys to prevent duplicate processing. We would implement vendor-specific template routing—attempting a cheaper, smaller model first, and escalating to a more capable model only upon validation failure. Documents would be triaged into a confidence-based human review queue. Comprehensive observability (tracking latency, cost per document, retry rates, and flag rates), PII redaction handlers, and a golden dataset for regression evaluations against new model versions would complete the enterprise architecture.

## Limitations and Future Work

- **OCR**: Currently rejects image-only or scanned documents. Integrating an OCR pipeline (e.g., Tesseract, AWS Textract) or multimodal LLM inputs is required.
- **Multi-Stop Documents**: Schema is currently limited to a single pickup and delivery. Requires schema expansion to handle an array of stops.
- **Multi-Document PDFs**: Assumes a single rate confirmation per file. Splitting and classifying batched PDFs is a needed enhancement.
- **Native PDF Input**: Instead of parsing text locally with `pdfplumber`, natively supplying the PDF to models supporting document uploads could improve layout-aware extraction.
