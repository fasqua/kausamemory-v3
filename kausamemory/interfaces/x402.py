"""x402 payment gate for Hosted mode.

Makes each memory operation payable: an agent pays a micropayment per call,
settled on Solana, before the tool runs. This turns KausaMemory into
memory-as-a-service that any agent can meter. The choke point is the operation,
not the data (the data stays the user's, encrypted).

This module is transport-agnostic and testable offline. It owns three things:
  1. pricing per tool,
  2. the 402 challenge (what a caller without a valid payment gets back),
  3. dual-auth routing: local/free callers bypass payment; hosted callers must
     present a valid payment.

Real settlement (verifying a Solana payment via an x402 facilitator) is injected
as a verifier callable, so the gate logic is exercised here without a wallet or
network. In production, plug a facilitator-backed verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Verifies a payment proof for (tool, amount). Returns True if settled/valid.
# In production this calls an x402 facilitator on Solana. Injected for testing.
PaymentVerifier = Callable[[str, str, int], bool]


class PaymentRequired(Exception):
    """Raised when a hosted caller has no valid payment. Carries the 402 challenge."""

    def __init__(self, challenge: dict) -> None:
        super().__init__("Payment Required")
        self.challenge = challenge


@dataclass
class Pricing:
    # micro-amounts in the token's smallest unit (e.g. USDC has 6 decimals).
    recipient: str
    token: str = "USDC"
    chain: str = "solana"
    per_tool: dict | None = None
    default_price: int = 500  # 0.0005 USDC

    def price(self, tool: str) -> int:
        if self.per_tool and tool in self.per_tool:
            return self.per_tool[tool]
        return self.default_price


class X402Gate:
    """Dual-auth gate.

    free_mode=True  -> Sovereign/local: every call bypasses payment.
    free_mode=False -> Hosted: a call must carry a payment proof that the verifier
                       accepts, otherwise a 402 challenge is raised.
    """

    def __init__(
        self,
        pricing: Pricing,
        verifier: PaymentVerifier | None = None,
        free_mode: bool = False,
    ) -> None:
        self.pricing = pricing
        self.verifier = verifier
        self.free_mode = free_mode

    def challenge(self, tool: str) -> dict:
        """The body/headers returned as HTTP 402 for an unpaid hosted call."""
        return {
            "status": 402,
            "reason": "Payment Required",
            "x402": {
                "amount": self.pricing.price(tool),
                "token": self.pricing.token,
                "chain": self.pricing.chain,
                "recipient": self.pricing.recipient,
                "resource": tool,
            },
        }

    def authorize(self, tool: str, payment_proof: str | None = None) -> None:
        """Raise PaymentRequired unless the call is allowed to proceed."""
        if self.free_mode:
            return  # Sovereign mode: no payment
        if payment_proof is None:
            raise PaymentRequired(self.challenge(tool))
        if self.verifier is None:
            raise PaymentRequired(self.challenge(tool))
        if not self.verifier(tool, self.pricing.token, self.pricing.price(tool)):
            raise PaymentRequired(self.challenge(tool))
        # settled: allowed to proceed


def guarded_call(gate: "X402Gate", tools, name: str, args: dict, payment_proof: str | None = None) -> dict:
    """Authorize (pay-per-call), then dispatch to MemoryTools."""
    gate.authorize(name, payment_proof)
    return tools.call(name, args)
