"""
conftest.py — Shared pytest fixtures for the freight_parser test suite.

These fixtures provide ready-made FreightDocument instances so individual test
modules never have to construct them by hand.  They are session-scoped where
possible to avoid rebuilding objects that are never mutated.
"""

import pytest

from freight_parser.schemas import FreightDocument, Location


# ---------------------------------------------------------------------------
# Document fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_doc() -> FreightDocument:
    """The intentionally flawed sample document described in the spec.

    Known violations:
    - RATE_MISMATCH  : 2200.00 + 350.00 = 2550.00 ≠ 2800.00
    - OVERWEIGHT_LOAD: 46,800 lbs > 45,000 lb limit
    """
    return FreightDocument(
        carrier_name="Apex Logistics Solutions LLC",
        load_number="LD-994821",
        pickup_location=Location(
            facility_name="Distribution Center 4",
            city="Dallas",
            state="TX",
            zip_code="75201",
        ),
        delivery_location=Location(
            facility_name="Warehouse B",
            city="Atlanta",
            state="GA",
            zip_code="30303",
        ),
        total_linehaul_rate=2200.00,
        fuel_surcharge=350.00,
        total_pay=2800.00,
        weight_lbs=46800,
    )


@pytest.fixture
def clean_doc() -> FreightDocument:
    """A fully populated, rule-compliant document that should be APPROVED.

    Rates: 2200.00 + 350.00 = 2550.00  (correct)
    Weight: 40,000 lbs  (below 45,000 lb limit)
    """
    return FreightDocument(
        carrier_name="Swift Freight Partners LLC",
        load_number="LD-000001",
        pickup_location=Location(
            facility_name="Warehouse Alpha",
            city="Dallas",
            state="TX",
            zip_code="75201",
        ),
        delivery_location=Location(
            facility_name="Distribution Hub 7",
            city="Atlanta",
            state="GA",
            zip_code="30303",
        ),
        total_linehaul_rate=2200.00,
        fuel_surcharge=350.00,
        total_pay=2550.00,
        weight_lbs=40000,
    )
