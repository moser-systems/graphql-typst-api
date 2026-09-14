"""Allow ``python -m graphql_typst_api`` as an alias for the console script."""

from graphql_typst_api.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
