"""Allow ``python -m graphql_typst`` as an alias for the console script."""

from graphql_typst.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
