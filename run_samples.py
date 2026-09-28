"""
run_samples.py -- Execute the freight_parser CLI against all sample files and
save outputs to sample_output/.

Runs:
  1. rate_confirmation.pdf  -> sample_output/sample_run_pdf.txt
  2. rate_confirmation.txt  -> sample_output/sample_run_txt.txt
                           -> sample_output/sample_decision.json  (from txt run)
  3. image_only.pdf         -> asserts exit code 2 and scanned-PDF message

Usage:
    python run_samples.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output so the report prints cleanly on all Windows terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VENV_PY = Path(".venv/Scripts/python")
SRC = Path("src")
DATA = Path("sample_data")
OUT = Path("sample_output")
OUT.mkdir(exist_ok=True)


def run_cli(
    file: str | None, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess:
    cmd = [str(VENV_PY), "-m", "freight_parser.cli"]
    if file:
        cmd += ["--file", file]
    if extra_args:
        cmd += extra_args
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONUTF8": "1"}
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )


def check_extracted_fields(label: str, decision_json: dict) -> list[str]:
    """Verify the extracted JSON matches all expected values. Returns list of failures."""
    failures = []
    data = decision_json.get("data") or {}
    pickup = data.get("pickup_location") or {}
    delivery = data.get("delivery_location") or {}

    checks = {
        "carrier_name":    ("Apex Logistics Solutions LLC", data.get("carrier_name")),
        "load_number":     ("LD-994821",                    data.get("load_number")),
        "pickup city":     ("Dallas",                       pickup.get("city")),
        "pickup state":    ("TX",                           pickup.get("state")),
        "pickup zip":      ("75201",                        pickup.get("zip_code")),
        "delivery city":   ("Atlanta",                      delivery.get("city")),
        "delivery state":  ("GA",                           delivery.get("state")),
        "delivery zip":    ("30303",                        delivery.get("zip_code")),
        "linehaul":        (2200.0,                         data.get("total_linehaul_rate")),
        "fuel":            (350.0,                          data.get("fuel_surcharge")),
        "total_pay":       (2800.0,                         data.get("total_pay")),
        "weight_lbs":      (46800,                          data.get("weight_lbs")),
        "status":          ("FLAGGED_FOR_HUMAN_REVIEW",     decision_json.get("status")),
    }

    print(f"\n{'='*62}")
    print(f"  FIELD VERIFICATION --- {label}")
    print(f"{'='*62}")
    for field, (expected, actual) in checks.items():
        ok = actual == expected
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"  {tag}  {field:<20s}  expected={str(expected):<35s}  got={actual!r}")
        if not ok:
            failures.append(f"{label}/{field}: expected {expected!r}, got {actual!r}")

    issue_codes = [i.get("code") for i in decision_json.get("issues", [])]
    for code in ("RATE_MISMATCH", "OVERWEIGHT_LOAD"):
        ok = code in issue_codes
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"  {tag}  issue/{code}")
        if not ok:
            failures.append(f"{label}: issue {code} missing")

    return failures


# ---------------------------------------------------------------------------
# 1. PDF run
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  RUN 1 -- rate_confirmation.pdf")
print("=" * 62)
pdf_result = run_cli(str(DATA / "rate_confirmation.pdf"))
pdf_output = pdf_result.stdout + pdf_result.stderr
(OUT / "sample_run_pdf.txt").write_text(pdf_output, encoding="utf-8")
print(pdf_result.stdout)
if pdf_result.stderr:
    print("[stderr]", pdf_result.stderr[:500])
print(f"Exit code: {pdf_result.returncode}")

pdf_decision: dict = {}
try:
    marker = "Full decision JSON:"
    if marker in pdf_result.stdout:
        pdf_decision = json.loads(pdf_result.stdout.split(marker, 1)[1].strip())
except Exception as exc:
    print(f"WARNING: could not parse PDF decision JSON: {exc}")

failures_pdf = check_extracted_fields("PDF", pdf_decision)

# ---------------------------------------------------------------------------
# 2. TXT run
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  RUN 2 -- rate_confirmation.txt")
print("=" * 62)
json_out = str(OUT / "sample_decision.json")
txt_result = run_cli(str(DATA / "rate_confirmation.txt"), ["--output", json_out])
txt_output = txt_result.stdout + txt_result.stderr
(OUT / "sample_run_txt.txt").write_text(txt_output, encoding="utf-8")
print(txt_result.stdout)
if txt_result.stderr:
    print("[stderr]", txt_result.stderr[:500])
print(f"Exit code: {txt_result.returncode}")

txt_decision: dict = {}
try:
    marker = "Full decision JSON:"
    if marker in txt_result.stdout:
        txt_decision = json.loads(txt_result.stdout.split(marker, 1)[1].strip())
except Exception as exc:
    print(f"WARNING: could not parse TXT decision JSON: {exc}")

failures_txt = check_extracted_fields("TXT", txt_decision)

# ---------------------------------------------------------------------------
# 3. Compare PDF vs TXT
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  COMPARISON -- PDF vs TXT extracted data")
print("=" * 62)
pdf_data = pdf_decision.get("data") or {}
txt_data = txt_decision.get("data") or {}
compare_keys = [
    "carrier_name", "load_number",
    "total_linehaul_rate", "fuel_surcharge", "total_pay", "weight_lbs",
]
all_match = True
for key in compare_keys:
    match = pdf_data.get(key) == txt_data.get(key)
    tag = "[MATCH]" if match else "[DIFF] "
    print(f"  {tag}  {key:<22s}  PDF={pdf_data.get(key)!r:<20}  TXT={txt_data.get(key)!r}")
    if not match:
        all_match = False

if all_match:
    print("\n  [PASS]  PDF and TXT produce identical extracted values.")
else:
    print("\n  [FAIL]  Mismatch detected between PDF and TXT runs.")

# ---------------------------------------------------------------------------
# 4. Image-only PDF
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  RUN 3 -- image_only.pdf  (expect exit code 2)")
print("=" * 62)
img_result = run_cli(str(DATA / "image_only.pdf"))
combined = img_result.stdout + img_result.stderr
print(combined)
print(f"Exit code: {img_result.returncode}")

scanned_ok = any(
    kw in combined.lower()
    for kw in ("scanned", "image-only", "text layer", "image_only")
)
code_ok = img_result.returncode == 2
print(f"\n  {'[PASS]' if code_ok    else '[FAIL]'}  Exit code == 2 : {img_result.returncode}")
print(f"  {'[PASS]' if scanned_ok else '[FAIL]'}  Scanned-PDF message present: {scanned_ok}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
all_failures = failures_pdf + failures_txt
print("\n" + "=" * 62)
print("  SUMMARY")
print("=" * 62)
if not all_failures and code_ok and scanned_ok:
    print("  [ALL PASS]  Every check passed.")
    sys.exit(0)
else:
    if all_failures:
        print("  [FAIL]  Field verification failures:")
        for f in all_failures:
            print(f"          {f}")
    if not code_ok:
        print(f"  [FAIL]  image_only.pdf exit code was {img_result.returncode}, expected 2")
    if not scanned_ok:
        print("  [FAIL]  Scanned-PDF message not found in output")
    sys.exit(1)
