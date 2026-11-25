# okf

Reader, validator and writer for Open Knowledge Format (OKF) v0.3 bundles.

- `Bundle.load(path)`: concepts, assets, root index metadata, link graph
- `trust_info(concept)`: trust tier (current verifications only), status, staleness, `superseded_by`
- `rank_conflicting(concepts)`: okf-consume's order (status, tier, freshness, `generated.at`)
- `validate(bundle)`: conformance errors and quality warnings
- `okf.writer`: round-trip frontmatter edits, index regeneration, `log.md` entries (needs `okf[write]`)

```bash
okf validate path/to/bundle
okf scan path/to/bundle --type decision --stale --json
```
