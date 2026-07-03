"""Head pointer: the single mutable value that says which snapshot is current.

Design: separate what changes (one small pointer) from what never changes
(immutable content-addressed snapshots). The head holds a CID plus a monotonic
sequence number. Monotonic seq gives anti-rollback and a canonical order for
free.

Implementations:
  - LocalHead:  a head.json file. For offline development and single-machine use.
  - SolanaHead: the on-chain PDA from solana-program/ (Phase 4). Cross-device,
                trustless discovery. Talks to the deployed kausamemory_head
                program. Solana libs are imported lazily, so LocalHead works with
                no extra dependencies and SolanaHead only needs them when used.
"""

from __future__ import annotations

import json
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Head:
    cid: str
    seq: int
    updated_at: float


class HeadPointer(ABC):
    @abstractmethod
    def read(self) -> Head | None:
        ...

    @abstractmethod
    def write(self, cid: str, seq: int, updated_at: float) -> str | None:
        """Must reject any write whose seq is not strictly greater than current."""


class LocalHead(HeadPointer):
    """File-based head for offline dev. Enforces monotonic seq, like the chain does."""

    def __init__(self, path: str) -> None:
        self.path = pathlib.Path(path)

    def read(self) -> Head | None:
        if not self.path.exists():
            return None
        d = json.loads(self.path.read_text())
        return Head(cid=d["cid"], seq=int(d["seq"]), updated_at=float(d["updated_at"]))

    def write(self, cid: str, seq: int, updated_at: float) -> None:
        current = self.read()
        if current is not None and seq <= current.seq:
            raise ValueError(f"non-monotonic head write: {seq} <= {current.seq}")
        self.path.write_text(json.dumps({"cid": cid, "seq": seq, "updated_at": updated_at}))


# A CID locator is "blake3:<hex>"; the program stores the raw 32 bytes.
def _cid_to_bytes(cid: str) -> bytes:
    raw = bytes.fromhex(cid.split(":", 1)[1])
    if len(raw) != 32:
        raise ValueError("CID must be a 32-byte blake3 hash")
    return raw


def _cid_from_bytes(raw: bytes) -> str:
    return "blake3:" + raw.hex()


class SolanaHead(HeadPointer):
    """On-chain head pointer backed by the kausamemory_head program.

    The monotonic guard is enforced on-chain by set_head, so a stale write is
    rejected by the program itself, not just locally. Requires the deployed
    program id and the owner's keypair (a solders Keypair) to sign writes.

    Reads decode the PDA account layout written by the program:
        8 (discriminator) + 32 (owner) + 32 (cid) + 8 (seq) + 8 (updated_at)
    """

    def __init__(self, rpc_url: str, program_id: str, keypair=None, owner_pubkey: str | None = None) -> None:
        self.rpc_url = rpc_url
        self.program_id = program_id
        self.keypair = keypair  # solders.keypair.Keypair for writes
        self._owner_pubkey = owner_pubkey

    def _pubkey(self):
        from solders.pubkey import Pubkey

        if self.keypair is not None:
            return self.keypair.pubkey()
        if self._owner_pubkey is not None:
            return Pubkey.from_string(self._owner_pubkey)
        raise ValueError("SolanaHead needs a keypair or owner_pubkey")

    def _pda(self):
        from solders.pubkey import Pubkey

        prog = Pubkey.from_string(self.program_id)
        pda, _bump = Pubkey.find_program_address([b"head", bytes(self._pubkey())], prog)
        return pda

    def read(self) -> Head | None:
        from solana.rpc.api import Client
        from solana.rpc.commitment import Confirmed

        client = Client(self.rpc_url, commitment=Confirmed)
        info = client.get_account_info(self._pda(), commitment=Confirmed).value
        if info is None:
            return None
        data = bytes(info.data)
        # skip 8-byte anchor discriminator + 32-byte owner
        off = 8 + 32
        cid = _cid_from_bytes(data[off : off + 32])
        seq = int.from_bytes(data[off + 32 : off + 40], "little")
        updated_at = int.from_bytes(data[off + 40 : off + 48], "little", signed=True)
        return Head(cid=cid, seq=seq, updated_at=float(updated_at))

    # Anchor instruction discriminator = first 8 bytes of sha256("global:set_head").
    _SET_HEAD_DISCRIMINATOR = bytes([47, 183, 190, 159, 23, 12, 121, 91])

    def write(self, cid: str, seq: int, updated_at: float) -> str | None:
        """Send a set_head instruction to the program. The on-chain guard rejects
        any seq that does not strictly increase, and updated_at is set by the
        chain clock (the argument is ignored, kept for the HeadPointer interface).
        Requires a signing keypair. Built by hand with solders, no IDL needed.

        Returns the transaction signature (base58) so a caller can show or store
        an on-chain proof of the update.
        """
        if self.keypair is None:
            raise ValueError("SolanaHead.write requires a signing keypair")

        from solders.pubkey import Pubkey
        from solders.instruction import Instruction, AccountMeta
        from solders.system_program import ID as SYSTEM_PROGRAM_ID
        from solders.transaction import VersionedTransaction
        from solders.message import MessageV0
        from solana.rpc.api import Client
        from solana.rpc.commitment import Confirmed

        program = Pubkey.from_string(self.program_id)
        owner = self.keypair.pubkey()
        pda = self._pda()

        # instruction data: discriminator + cid[32] + seq as u64 little-endian
        data = self._SET_HEAD_DISCRIMINATOR + _cid_to_bytes(cid) + int(seq).to_bytes(8, "little")

        accounts = [
            AccountMeta(pubkey=pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner, is_signer=True, is_writable=True),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        ix = Instruction(program_id=program, data=data, accounts=accounts)

        client = Client(self.rpc_url, commitment=Confirmed)
        blockhash = client.get_latest_blockhash().value.blockhash
        # Versioned transaction: this solana-py build only accepts VersionedTransaction.
        msg = MessageV0.try_compile(owner, [ix], [], blockhash)
        tx = VersionedTransaction(msg, [self.keypair])
        try:
            sig = client.send_raw_transaction(bytes(tx)).value
            client.confirm_transaction(sig, commitment=Confirmed)
        except Exception as exc:
            # The program raises custom error 6000 (NonMonotonicSeq) when seq
            # does not strictly increase. Surface it as a clear typed error
            # instead of a raw RPC exception, so callers can handle rollback.
            text = str(exc)
            if "6000" in text or "0x1770" in text or "NonMonotonicSeq" in text:
                raise ValueError(
                    "non-monotonic head write rejected on-chain: "
                    "seq must strictly increase (anti-rollback)"
                ) from exc
            raise
        return str(sig)
