# NSE TL Parquet Data {{VERSION}}

Released on **{{DATE}} at {{TIME}} UTC** from commit `{{SHORT_COMMIT}}`.

## Package summary

- **Version:** {{VERSION}}
- **Parquet files:** {{SOURCE_FILES}}
- **Archive parts:** {{ASSET_COUNT}}
- **Source commit:** `{{COMMIT}}`

## Archive assets

| Asset | Parquet files | Source size | Compressed size |
|---|---:|---:|---:|
{{ASSET_TABLE}}

Archives retain repository-relative paths such as
`database/r/RELIANCE/tl.parquet`. Every archive is checked for integrity and
kept below the configured release-asset limit.

The release also contains `RELEASE_MANIFEST.json`, `SHA256SUMS.txt`,
`RELEASE_NOTES-{{VERSION}}.md`, and `LICENSE`.

This release is created manually with a version such as `v1.0.0`. Rerunning
the same version replaces its tag, metadata, and assets.

The data is supplied without warranty and is not investment advice.
