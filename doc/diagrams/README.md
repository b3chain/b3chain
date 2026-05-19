# B3PoW-Scratch v1.1 launch diagrams

Mermaid (`.mmd`) source files for the launch-package diagrams. Rendered
to SVG and PDF locally via [mermaid-cli](https://github.com/mermaid-js/mermaid-cli)
(`mmdc`) into `./out/` (gitignored — operators build locally and never
commit rendered artifacts).

## Diagrams

| Source | What it shows | Embedded in |
|---|---|---|
| [`system-launch.mmd`](system-launch.mmd) | Launch-time deployment: 3 testnet seeds, b3chaind full nodes, reference pool (Stratum), CPU + FPGA reference miners, block explorer, faucet, status monitor, website. Edges labelled with P2P / RPC / Stratum / share + block submission / JSON polling traffic. | [`B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) §1 (Introduction); [b3chain-website/testnet.html](../../../b3chain-website/testnet.html). |
| [`algorithm-dataflow.mmd`](algorithm-dataflow.mmd) | Per-hash data flow: 80 B header + 32 B `prev_block_hash` → BLAKE3 seed → `init_scratchpad` (BLAKE3-XOF × 16 384 → 1 MiB) → `init_lanes` (8 × 32 B) → 2 048-iteration RMW loop (`derive_addresses` → `parallel_read` → `mix_step` → write-back) → final BLAKE3(lanes ‖ nonce) → 32 B `pow_hash`. Byte sizes labelled at every interface. | [`B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) §4.3 (Top-level pipeline); [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) §5 (Top-level function). |
| [`scratchpad-layout.mmd`](scratchpad-layout.mmd) | 1 MiB scratchpad split into 8 contiguous 128 KiB lane partitions (2 048 × 64 B blocks each). Per-iteration 64 B window, addresses derived from prior lane state, RMW write-back to the same offset. Lanes never read across partitions. | [`B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) §4.4 (`init_scratchpad`); [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) §6.1 + Appendix A. |
| [`hardware-ranking.mmd`](hardware-ranking.mmd) | Hardware classes ranked by hashrate-per-watt on B3PoW-Scratch: B3Miner-1 KU5P FPGA (reference miner, solid stroke), hypothetical ASIC port (dashed), high-end CPU (dashed), high-end GPU (dashed). Stroke convention: solid = measured / shipped artifact, dashed = order-of-magnitude estimate. | [`B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) §6.4 (Hardware ranking summary); [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) §8.D. |
| [`verification-flow.mmd`](verification-flow.mmd) | What a `b3chaind` node runs when verifying an inbound block: header parse → context-free pre-checks → `CheckBlockHeaderPoW` (LRU pad lookup, wall-clock budget) → `b3pow::Hash` → target compare → remainder of validation pipeline (merkle, tx, contextual) → accept / reject. Filepath labels (`src/pow.cpp::…`, `src/crypto/b3pow_scratch.cpp::…`, `src/validation.cpp::…`) on every node. | [`B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) §7 (Verification cost on the node); [`doc/SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md). |

## Build

```
make svg      # render every .mmd to out/*.svg
make pdf      # render every .mmd to out/*.pdf
make all      # both
make check    # parse-only sanity check (no artifacts kept)
make clean    # remove out/
```

If `mmdc` is not on `PATH`, every target except `clean` prints:

```
ERROR: mermaid-cli (mmdc) is not installed.
Install with: npm install -g @mermaid-js/mermaid-cli
```

The Makefile uses a `%.svg: %.mmd` pattern rule, so adding a new diagram
is just `git add foo.mmd` plus a row in the table above. No Makefile
edits required.

## Whitepaper render order

The whitepaper Makefile at [`../whitepaper/Makefile`](../whitepaper/Makefile)
renders Markdown → PDF via pandoc + XeLaTeX. It already sets
`--resource-path=.:../diagrams`, so image references of the form
`![…](../diagrams/out/foo.svg)` resolve against this directory. **Build
the diagrams first**, then the whitepaper:

```
cd doc/diagrams  && make svg
cd ../whitepaper && make pdf
```

`out/` is gitignored. CI builds run both `make` invocations in the
same job; see [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
when that lands as part of launch-package Phase 2.3.

## Editing conventions

| When you change | Update |
|---|---|
| The algorithm itself (parameters in [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) §3, the top-level loop in §5, `mix_step` in §6.5, the `ITER_MUL` constants in §3) | [`algorithm-dataflow.mmd`](algorithm-dataflow.mmd) and [`scratchpad-layout.mmd`](scratchpad-layout.mmd). Run `make check`, then re-render the whitepaper PDF. |
| Hardware bring-up topology (seeds, pool, explorer, faucet, miners on the live testnet) | [`system-launch.mmd`](system-launch.mmd). If the operator-facing topology shifts, also touch [`b3chain-website/testnet.html`](../../../b3chain-website/testnet.html). |
| The hardware-ranking table in [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) §8.D or the whitepaper §6.4 table | [`hardware-ranking.mmd`](hardware-ranking.mmd). Keep dashed stroke on every estimated tier; flip to solid only once an `contrib/testing/bench/results/r0/` bench result lands. |
| Validation code paths in `src/pow.cpp`, `src/validation.cpp`, `src/crypto/b3pow_scratch.cpp`, or `src/primitives/block.cpp` | [`verification-flow.mmd`](verification-flow.mmd). Keep filepath labels accurate — they double as a static call-graph for new contributors. |

## Tooling notes

- Tested against mermaid-cli ≥ 10.x. The `flowchart` and `subgraph`
  syntax used here is in mermaid core since 8.x; no plugins required.
- No external image dependencies — every diagram is a self-contained
  `.mmd` source.
- `hardware-ranking.mmd` is hand-rolled as a vertical-stack flowchart
  rather than `xychart-beta`: the beta chart type does not render
  reliably under mermaid-cli 10.x + pandoc image embed, so we trade
  exact bar widths for portability. Text-encoded bars (`████`, `▌`,
  `·`) convey relative ordering.
- All edge labels are quoted (`A -->|"text"| B`) to avoid parser
  surprises around `=`, `<`, `>`, and other special characters.
