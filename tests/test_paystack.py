"""Day 16: the Paystack integration on its own (no database, no network)."""

import hashlib
import hmac

from app.integrations import paystack


def test_a_signature_is_the_hmac_sha512_of_the_raw_body():
    body = b'{"event":"charge.success"}'
    good = hmac.new(b"sk_test_abc", body, hashlib.sha512).hexdigest()
    assert paystack.valid_signature(body, good, "sk_test_abc")
    assert not paystack.valid_signature(body, good, "sk_test_other")
    assert not paystack.valid_signature(body + b" ", good, "sk_test_abc")
    assert not paystack.valid_signature(body, None, "sk_test_abc")
    assert not paystack.valid_signature(body, good, "")


def test_references_are_unique_and_safe():
    references = {paystack.new_reference() for _ in range(200)}
    assert len(references) == 200
    for reference in references:
        assert reference.startswith("cl_") and reference.replace("_", "").isalnum()
