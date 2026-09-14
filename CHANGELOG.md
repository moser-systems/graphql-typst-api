# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-08

Initial release.

### Added

- `POST /v1/render/{name}` renders a configured template to `application/pdf`, plus
  `GET /v1/templates`, `/healthz`, `/readyz` and an optional `/metrics`.
- Template bundles: a directory pairing a Typst template with a GraphQL query, a
  JMESPath transform and optional defaults, fully validated at startup with every
  problem reported at once.
- Request arguments are passed as GraphQL variables, with names and types derived from
  the query's own variable definitions.
- Three-layer data precedence (global defaults, template defaults, transform output)
  with `null` pruning so an omitted upstream field falls back to its default.
- Optional static API key on `/v1`; upstream authentication via a configurable header.
- `graphql-typst` CLI with `serve`, `render`, `check`, `warm-cache` and `version`.
- Multi-architecture container image (amd64, arm64) with fonts and `@preview` packages
  baked in, so rendering needs no network at runtime.

[Unreleased]: https://github.com/resmo/graphql-typst/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/resmo/graphql-typst/releases/tag/v0.1.0
