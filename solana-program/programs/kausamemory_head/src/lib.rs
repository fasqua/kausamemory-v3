// KausaMemory head-pointer program.
//
// One PDA per owner storing the CID of their latest encrypted snapshot plus a
// monotonic sequence number. This is discovery + canonical ordering for the
// self-sovereign sync layer: clients read the PDA to find the current snapshot,
// and the monotonic guard gives anti-rollback for free. The program never sees
// plaintext or keys; it only stores a 32-byte content hash and a counter.

use anchor_lang::prelude::*;

declare_id!("4VfiKtC5LXu5R72gKR9UwtRcFJ21uQsSMDSyTiAWdjR4");

#[program]
pub mod kausamemory_head {
    use super::*;

    // Create or update the caller's head pointer. Rejects any seq that does not
    // strictly increase, so an old snapshot can never overwrite a newer one.
    pub fn set_head(ctx: Context<SetHead>, cid: [u8; 32], seq: u64) -> Result<()> {
        let head = &mut ctx.accounts.head;
        require!(seq > head.seq, HeadError::NonMonotonicSeq);
        head.owner = ctx.accounts.owner.key();
        head.cid = cid;
        head.seq = seq;
        head.updated_at = Clock::get()?.unix_timestamp;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct SetHead<'info> {
    #[account(
        init_if_needed,
        payer = owner,
        space = 8 + MemoryHead::LEN,
        seeds = [b"head", owner.key().as_ref()],
        bump
    )]
    pub head: Account<'info, MemoryHead>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[account]
pub struct MemoryHead {
    pub owner: Pubkey,      // 32
    pub cid: [u8; 32],      // 32  (BLAKE3 of the latest encrypted snapshot)
    pub seq: u64,           // 8   (monotonic)
    pub updated_at: i64,    // 8
}

impl MemoryHead {
    pub const LEN: usize = 32 + 32 + 8 + 8;
}

#[error_code]
pub enum HeadError {
    #[msg("seq must strictly increase (anti-rollback)")]
    NonMonotonicSeq,
}
