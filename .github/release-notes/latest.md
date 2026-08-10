# Latest NSE TL Parquet Data

Updated on **{{DATE}} at {{TIME}} UTC** from commit `{{SHORT_COMMIT}}`.

Trigger: `{{COMMIT_MESSAGE}}`

## Package summary

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
`RELEASE_NOTES.md`, and `LICENSE`.

This rolling release is replaced when a commit whose message begins with
`RC:` is pushed to `main`, or when the workflow is manually forced. The mutable
tag is `nse-tl-latest`.

The data is supplied without warranty and is not investment advice.
