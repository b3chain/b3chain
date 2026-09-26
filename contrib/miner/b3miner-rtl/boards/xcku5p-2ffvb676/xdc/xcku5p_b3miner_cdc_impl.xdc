# Implementation-only constraints for bundled-data CDC mailboxes. Payload is
# held stable until its synchronized request toggle is acknowledged.

set_max_delay -datapath_only 8.000 \
    -from [get_cells -quiet -hier -regexp {.*u_cdc/(cmd_mailbox_reg.*|nonce_start_mailbox_reg.*|nonce_end_mailbox_reg.*|nonce_count_mailbox_reg.*|prev_hash_mailbox_reg.*|target_mailbox_reg.*|header_mailbox_reg.*)}] \
    -to [get_cells -quiet -hier -regexp {.*u_cdc/(cmd_mailbox_mine_reg.*|mine_nonce_start_reg.*|mine_nonce_end_reg.*|mine_nonce_count_reg.*|mine_prev_hash_reg.*|mine_share_target_reg.*|mine_header_prefix_reg.*)}]
set_bus_skew 4.000 \
    -from [get_cells -quiet -hier -regexp {.*u_cdc/(cmd_mailbox_reg.*|nonce_start_mailbox_reg.*|nonce_end_mailbox_reg.*|nonce_count_mailbox_reg.*|prev_hash_mailbox_reg.*|target_mailbox_reg.*|header_mailbox_reg.*)}] \
    -to [get_cells -quiet -hier -regexp {.*u_cdc/(cmd_mailbox_mine_reg.*|mine_nonce_start_reg.*|mine_nonce_end_reg.*|mine_nonce_count_reg.*|mine_prev_hash_reg.*|mine_share_target_reg.*|mine_header_prefix_reg.*)}]

set_max_delay -datapath_only 20.000 \
    -from [get_cells -quiet -hier -regexp {.*u_cdc/(share_nonce_lo_mailbox_reg.*|share_nonce_hi_mailbox_reg.*|share_ntime_mailbox_reg.*|share_hash_mailbox_reg.*)}] \
    -to [get_cells -quiet -hier -regexp {.*u_cdc/(sys_nonce_lo_reg.*|sys_nonce_hi_reg.*|sys_ntime_reg.*|sys_pow_hash_reg.*)}]
set_bus_skew 10.000 \
    -from [get_cells -quiet -hier -regexp {.*u_cdc/(share_nonce_lo_mailbox_reg.*|share_nonce_hi_mailbox_reg.*|share_ntime_mailbox_reg.*|share_hash_mailbox_reg.*)}] \
    -to [get_cells -quiet -hier -regexp {.*u_cdc/(sys_nonce_lo_reg.*|sys_nonce_hi_reg.*|sys_ntime_reg.*|sys_pow_hash_reg.*)}]
