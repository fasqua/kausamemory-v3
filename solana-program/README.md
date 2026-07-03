# KausaMemory head-pointer program (Phase 4)

One PDA per owner: {owner, cid[32], seq, updated_at}. `set_head(cid, seq)` asserts
seq strictly increases (anti-rollback) and that the signer owns the account.

## Deploy (needs the Anchor toolchain and SOL)

    anchor build
    anchor deploy --provider.cluster devnet

Then replace the placeholder in `declare_id!` and in the Python client
(`kausamemory/solana/head.py`, SolanaHead) with the deployed program id.

The program stores only a content hash and a counter. No plaintext, no keys.
