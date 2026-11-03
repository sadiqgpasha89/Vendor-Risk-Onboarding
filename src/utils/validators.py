"""Validation utilities for vendor business data."""

import re
from typing import Tuple, Optional


def validate_tax_id(tax_id: str, country_code: str = "US") -> Tuple[bool, str]:
    """Validate tax identification number based on country format."""
    if not tax_id:
        return False, "Tax ID cannot be empty"

    clean_id = re.sub(r"[\s\-_]", "", tax_id).upper()

    if country_code.upper() in ("US", "USA"):
        # US EIN: 9 digits (XX-XXXXXXX) or SSN: 9 digits
        if len(clean_id) == 9 and clean_id.isdigit():
            return True, "Valid US EIN format"
        return False, f"Invalid US EIN format '{tax_id}'. Expected 9 digits."

    elif country_code.upper() in ("GB", "UK"):
        # UK VAT (9 or 12 digits) or UK Companies House CRN (8 characters)
        if re.match(r"^(GB)?\d{9}(\d{3})?$", clean_id) or len(clean_id) == 8 or (clean_id.startswith("GB") and len(clean_id) in (8, 10, 11)):
            return True, "Valid UK registration/VAT format"
        return False, f"Invalid UK VAT/CRN format '{tax_id}'."

    elif country_code.upper() in ("DE", "FR", "IT", "ES", "NL"):
        # EU VAT basic check
        if re.match(r"^[A-Z]{2}[0-9A-Z]{2,12}$", clean_id):
            return True, "Valid EU VAT format"
        return False, f"Invalid EU VAT format '{tax_id}'."

    elif country_code.upper() in ("IN", "IND"):
        # Indian GSTIN: 15 alphanumeric characters
        if re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$", clean_id):
            return True, "Valid GSTIN format"
        return False, f"Invalid Indian GSTIN format '{tax_id}'."

    # Generic global check
    if len(clean_id) >= 5 and re.match(r"^[A-Z0-9]+$", clean_id):
        return True, "Valid alphanumeric identifier"
    return False, f"Invalid tax identifier '{tax_id}'."


def validate_iban(iban: str) -> Tuple[bool, str]:
    """Validate International Bank Account Number (IBAN) using MOD-97 algorithm."""
    if not iban:
        return False, "IBAN cannot be empty"

    clean_iban = re.sub(r"[\s\-_]", "", iban).upper()

    # Length check: 14 to 34 characters
    if not (14 <= len(clean_iban) <= 34):
        return False, f"IBAN length must be between 14 and 34 characters (got {len(clean_iban)})."

    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", clean_iban):
        return False, "Invalid IBAN structure (must start with 2-letter country code followed by 2 check digits)."

    # MOD-97 Checksum
    rearranged = clean_iban[4:] + clean_iban[:4]
    numeric_str = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)

    try:
        if int(numeric_str) % 97 == 1:
            return True, "Valid IBAN checksum"
        return False, "Invalid IBAN checksum"
    except ValueError:
        return False, "Could not compute IBAN checksum"


def validate_swift_bic(bic: str) -> Tuple[bool, str]:
    """Validate SWIFT / BIC code (8 or 11 characters)."""
    if not bic:
        return False, "SWIFT/BIC cannot be empty"

    clean_bic = re.sub(r"[\s\-_]", "", bic).upper()
    # Format: 4 letters (bank), 2 letters (country), 2 alphanumeric (location), optional 3 alphanumeric (branch)
    if re.match(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$", clean_bic):
        return True, "Valid SWIFT/BIC code"
    return False, f"Invalid SWIFT/BIC code format '{bic}'. Expected 8 or 11 characters (e.g. CHASUS33XXX)."


def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email address format and disposable domain."""
    if not email:
        return False, "Email cannot be empty"

    regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(regex, email.strip()):
        return False, f"Invalid email format '{email}'"

    disposable_domains = {"mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com"}
    domain = email.split("@")[-1].lower()
    if domain in disposable_domains:
        return False, f"Disposable email address detected: '{domain}'"

    return True, "Valid email format"
