# Final Regional Graph Pipeline

This is the production pipeline used for the finalized regional music graph.
It combines deterministic extraction/classification, manual review cleanup, and
derived graph rebuilds. Older exploratory review batches and planning docs are
not part of this pipeline.

## Backup

Take a database backup before changing the graph:

```sh
mkdir -p backups
docker exec -i wiki-genres-postgres pg_dump \
  -U wiki_genres \
  -d wiki_genres \
  --format=custom \
  --no-owner \
  --no-privileges \
  > backups/wiki_genres_final_region_pipeline_YYYYMMDD_HHMMSS.dump
```

Current backup from the final reviewed state after regional variation
candidate cleanup:

```text
backups/wiki_genres_after_variant_candidate_cleanup_20260525_042637.dump
```

## Final Build Steps

Run region ownership classification with the region-mention majority classifier:

```sh
.venv/bin/python -m wiki_genres.cli classify-region-genre-ownership-v2 --sample 10
```

Apply the hierarchy/accessibility pass:

```sh
.venv/bin/python -m wiki_genres.cli apply-region-hierarchy-pass --sample 15
```

Canonicalize demonym/style proxy regions into the real regional nodes:

```sh
.venv/bin/python -m wiki_genres.cli canonicalize-region-alias-proxies --sample 30
```

Apply the manually reviewed remaining-region cleanup:

```sh
.venv/bin/python -m wiki_genres.cli apply-region-post-review-cleanup --sample 30
```

Promote accepted regional nodes and edges into the graph:

```sh
docker exec -i wiki-genres-postgres psql \
  -U wiki_genres \
  -d wiki_genres \
  < migrations/0026_promote_regions_to_genres.sql
```

Rebuild derived graph indexes:

```sh
.venv/bin/python -m wiki_genres.cli index-inbound-relationships --sample 0
.venv/bin/python -m wiki_genres.cli guard-genre-direction --sample 0
.venv/bin/python -m wiki_genres.cli flag-circular-relationships --sample 0
.venv/bin/python -m wiki_genres.cli index-music-reachability --sample 0
.venv/bin/python -m wiki_genres.cli index-genre-colors --sample 0
```

Generate the final readiness audit:

```sh
.venv/bin/python -m wiki_genres.cli audit-region-production-readiness \
  --output-dir tmp/region_production_after_mini_report_line_audit_final \
  --sample 20
```

Regenerate the regional documentation snapshots:

```sh
.venv/bin/python scripts/generate_region_docs.py
```

## Manual Review Cleanup Scope

`apply-region-post-review-cleanup` encodes the manually reviewed final issue
resolutions:

- rejects sovereign/territory alias leaks
- suppresses collapsed/rejected/source nodes from display promotion
- canonicalizes demonym/style proxy regions into real countries or regions
- accepts city exceptions only when they have final named genres
- hides or rejects cities without final genres
- resolves inferred regional variation candidates when they duplicate existing
  concrete variant pages, or when fuzzy normalization shows they are just a
  region/demonym-prefixed form of an already accepted base style for that region
- normalizes valid regional display titles
- deduplicates accepted region and graph-affecting region-genre evidence rows
- adds missing specific regional parent routes where needed

The final manual-review line audit verified the consolidated remaining-region
report, including:

- wrong parent routing
- collapsed/rejected display leaks
- demonym/style proxy nodes
- city visibility conflicts
- title/source metadata leakage
- graph-affecting duplicate display edges
- policy rows for territories, cultural regions, and historical/cross-border
  regions

## Final Expected Audit

The final production audit should report:

```text
production ready:                   True
promoted regions:                   437
zero-child promoted regions:        0
parentless promoted regions:        0
alias/style proxy candidates:       0
invalid promoted region titles:     0
duplicate region-genre pairs:       0
graph-affecting needs-review rows:  0
pending candidate rows:             0
```

The current final audit is stored at:

```text
tmp/region_production_after_mini_report_line_audit_final/region_production_audit.md
```
