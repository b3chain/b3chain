# Audit Page Tutorials

One markdown file per audit. Each is injected non-destructively into the
matching page in `b3chain-website/testing/audit-*.html` by
[`inject-tutorial.py`](../inject-tutorial.py).

## Layout per tutorial

Every tutorial follows the same five-part structure:

1. **The problem in one sentence**.
2. **The theory** — math and / or diagram.
3. **The hands-on demo** — what to run, expected output.
4. **An exercise** — a small change to the code that should make the audit fail.
5. **Further reading** — papers / BIPs / mailing-list threads.

## Wiring

The injector looks for an HTML comment marker in the target page:

```html
<!-- TUTORIAL -->
```

If found, the tutorial markdown is rendered to HTML and inserted between
that marker and the matching `<!-- /TUTORIAL -->` comment (or appended
inside a new `<section class="tutorial">` if no closing marker exists).

The injector is idempotent: re-running with a modified markdown file
overwrites the previous block; re-running with the same markdown
produces zero diff.

## Running

```bash
python3 contrib/testing/audit/inject-tutorial.py \
    --website ../b3chain-website
```

Or single-page:

```bash
python3 contrib/testing/audit/inject-tutorial.py \
    --website ../b3chain-website \
    --only audit-supply-cap
```
