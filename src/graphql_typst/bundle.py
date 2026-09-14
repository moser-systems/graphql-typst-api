"""Loading and validating a template bundle.

A bundle is a directory that pairs a Typst template with the GraphQL query that
feeds it, the JMESPath transform that reshapes the response, and optional static
defaults. The directory is also the Typst compilation root, so templates refer to
their siblings with root-absolute paths (``#import "/lib/page.typ"``).

Validation is a pure function of the directory, which is what makes
``graphql-typst check`` and the malformed-bundle test fixtures cheap. It collects
*all* problems and raises one :class:`BundleConfigError`, so an operator fixes a
broken bundle in one pass instead of one restart per mistake.
"""

from __future__ import annotations

import json
import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import jmespath
import yaml
from graphql import (
    DocumentNode,
    GraphQLSyntaxError,
    ListTypeNode,
    NamedTypeNode,
    NonNullTypeNode,
    OperationDefinitionNode,
    OperationType,
    TypeNode,
    parse,
    print_ast,
)
from jmespath.exceptions import JMESPathError
from jmespath.parser import ParsedResult
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from graphql_typst.errors import BundleConfigError, TemplateNotFoundError

CONFIG_FILENAME = "templates.yaml"

TemplateName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


class TemplateConfig(BaseModel):
    """One entry of ``templates:`` in ``templates.yaml``."""

    model_config = ConfigDict(extra="forbid")

    name: TemplateName
    description: str | None = None
    template: Path
    query: Path
    transform: Path | None = None
    defaults: Path | None = None
    args: list[str] | None = None
    operation_name: str | None = None
    filename: str | None = None


class BundleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    defaults: Path | None = None
    templates: Annotated[list[TemplateConfig], Field(min_length=1)]


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """A single GraphQL variable the template accepts."""

    name: str
    gql_type: str
    named_type: str
    required: bool
    has_default: bool
    is_list: bool


@dataclass(frozen=True, slots=True)
class LoadedTemplate:
    """A validated template, ready to serve requests."""

    name: str
    description: str | None
    template_path: Path
    query_source: str
    document: DocumentNode
    operation_name: str | None
    args: Mapping[str, ArgSpec]
    transform: ParsedResult | None
    defaults: Mapping[str, Any]
    filename_pattern: str


@dataclass(frozen=True, slots=True)
class Bundle:
    root: Path
    global_defaults: Mapping[str, Any] = field(default_factory=dict)
    templates: Mapping[str, LoadedTemplate] = field(default_factory=dict)

    def get(self, name: str) -> LoadedTemplate:
        try:
            return self.templates[name]
        except KeyError:
            raise TemplateNotFoundError(name, sorted(self.templates)) from None

    def names(self) -> list[str]:
        return sorted(self.templates)


def _unwrap(node: TypeNode) -> tuple[str, bool]:
    """Return the innermost named type and whether a list appears anywhere."""
    is_list = False
    current = node
    while True:
        if isinstance(current, NonNullTypeNode):
            current = current.type
        elif isinstance(current, ListTypeNode):
            is_list = True
            current = current.type
        elif isinstance(current, NamedTypeNode):
            return current.name.value, is_list
        else:  # pragma: no cover - graphql-core has no other type nodes
            raise TypeError(f"unexpected type node {type(current).__name__}")


def _arg_specs(operation: OperationDefinitionNode) -> dict[str, ArgSpec]:
    specs: dict[str, ArgSpec] = {}
    for var in operation.variable_definitions or ():
        named, is_list = _unwrap(var.type)
        has_default = var.default_value is not None
        specs[var.variable.name.value] = ArgSpec(
            name=var.variable.name.value,
            gql_type=print_ast(var.type),
            named_type=named,
            required=isinstance(var.type, NonNullTypeNode) and not has_default,
            has_default=has_default,
            is_list=is_list,
        )
    return specs


def strip_jmespath_comments(source: str) -> str:
    """Drop ``#`` comment lines from a transform file.

    JMESPath has no comment syntax, but a transform that maps thirty GraphQL fields
    onto template keys badly wants annotations, so full-line comments are stripped
    before compiling. Blank lines are kept so error line numbers stay meaningful.
    """
    return "\n".join("" if line.lstrip().startswith("#") else line for line in source.splitlines())


def load_defaults_file(path: Path) -> dict[str, Any]:
    """Load a defaults document. Raises ``ValueError`` if it is not a mapping."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        # ValueError, not TypeError: this is a malformed *file*, which the loader
        # turns into a config problem, not a programming error.
        raise ValueError(  # noqa: TRY004
            f"expected a mapping at the top level, got {type(data).__name__}"
        )
    return data


class _Loader:
    """Accumulates problems while walking the bundle, so all are reported at once."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.problems: list[str] = []

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def resolve_in_root(self, rel: Path, label: str) -> Path | None:
        if rel.is_absolute():
            self.fail(f"{label}: absolute paths are not allowed ({rel})")
            return None
        if ".." in rel.parts:
            self.fail(f"{label}: '..' is not allowed in bundle paths ({rel})")
            return None
        # .resolve() also collapses symlinks, so this rejects a symlink pointing out
        # of the bundle, not just a literal traversal.
        resolved = (self.root / rel).resolve()
        if not resolved.is_relative_to(self.root):
            self.fail(f"{label}: {rel} escapes the bundle directory")
            return None
        if not resolved.is_file():
            self.fail(f"{label}: file not found ({rel})")
            return None
        return resolved

    def load_defaults(self, rel: Path, label: str) -> dict[str, Any]:
        path = self.resolve_in_root(rel, label)
        if path is None:
            return {}
        if path.suffix not in (".json", ".yaml", ".yml"):
            self.fail(f"{label}: expected a .json, .yaml or .yml file ({rel})")
            return {}
        try:
            return load_defaults_file(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
            self.fail(f"{label}: cannot load {rel}: {exc}")
            return {}

    def load_query(
        self, rel: Path, label: str, operation_name: str | None
    ) -> tuple[str, DocumentNode, OperationDefinitionNode] | None:
        path = self.resolve_in_root(rel, label)
        if path is None:
            return None
        source = path.read_text(encoding="utf-8")
        try:
            document = parse(source)
        except GraphQLSyntaxError as exc:
            self.fail(f"{label}: {rel} is not valid GraphQL: {exc.message}")
            return None

        operation = self._select_operation(document, rel, label, operation_name)
        if operation is None:
            return None
        if operation.operation is not OperationType.QUERY:
            # Rendering a PDF must be side-effect free: the same request is retried by
            # clients, load balancers and the reconnecting gql session.
            self.fail(
                f"{label}: {rel} is a {operation.operation.value}; only queries can back a template"
            )
            return None
        return source, document, operation

    def _select_operation(
        self, document: DocumentNode, rel: Path, label: str, operation_name: str | None
    ) -> OperationDefinitionNode | None:
        operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
        if not operations:
            self.fail(f"{label}: {rel} contains no operation")
            return None
        if operation_name is not None:
            for candidate in operations:
                if candidate.name and candidate.name.value == operation_name:
                    return candidate
            found = sorted(o.name.value for o in operations if o.name)
            self.fail(f"{label}: no operation named {operation_name!r} in {rel} (found {found})")
            return None
        if len(operations) > 1:
            found = sorted(o.name.value for o in operations if o.name)
            self.fail(
                f"{label}: {rel} defines {len(operations)} operations {found}; "
                "set operation_name to pick one"
            )
            return None
        return operations[0]

    def load_transform(self, rel: Path, label: str) -> ParsedResult | None:
        path = self.resolve_in_root(rel, label)
        if path is None:
            return None
        try:
            return jmespath.compile(strip_jmespath_comments(path.read_text(encoding="utf-8")))
        except (JMESPathError, ValueError) as exc:
            self.fail(f"{label}: {rel} is not a valid JMESPath expression: {exc}")
            return None

    def check_filename(self, pattern: str, label: str, arg_names: set[str]) -> str | None:
        allowed = arg_names | {"name"}
        try:
            fields = list(string.Formatter().parse(pattern))
        except ValueError as exc:
            self.fail(f"{label}: invalid filename pattern {pattern!r}: {exc}")
            return None
        for _literal, field_name, _spec, _conversion in fields:
            if field_name is None:
                continue
            if field_name == "" or field_name.isdigit():
                self.fail(f"{label}: filename pattern must use named fields, not {{{field_name}}}")
                return None
            if "." in field_name or "[" in field_name:
                self.fail(
                    f"{label}: filename pattern field {field_name!r} may not use attribute "
                    "or item access"
                )
                return None
            if field_name not in allowed:
                self.fail(
                    f"{label}: filename pattern references unknown field {field_name!r} "
                    f"(available: {sorted(allowed)})"
                )
                return None
        return pattern

    def load_template(self, entry: TemplateConfig) -> LoadedTemplate | None:
        label = f"template '{entry.name}'"

        template_path = self.resolve_in_root(entry.template, f"{label}.template")
        query = self.load_query(entry.query, f"{label}.query", entry.operation_name)

        transform: ParsedResult | None = None
        if entry.transform is not None:
            transform = self.load_transform(entry.transform, f"{label}.transform")
            if transform is None:
                return None

        defaults: dict[str, Any] = {}
        if entry.defaults is not None:
            defaults = self.load_defaults(entry.defaults, f"{label}.defaults")

        if template_path is None or query is None:
            return None
        if template_path.suffix != ".typ":
            self.fail(f"{label}.template: expected a .typ file ({entry.template})")
            return None

        query_source, document, operation = query
        args = _arg_specs(operation)

        if entry.args is not None and set(entry.args) != set(args):
            self.fail(
                f"{label}.args {sorted(set(entry.args))} does not match the query's "
                f"variables {sorted(args)}"
            )
            return None

        pattern = self.check_filename(entry.filename or "{name}.pdf", label, set(args))
        if pattern is None:
            return None

        return LoadedTemplate(
            name=entry.name,
            description=entry.description,
            template_path=template_path,
            query_source=query_source,
            document=document,
            operation_name=entry.operation_name
            or (operation.name.value if operation.name else None),
            args=args,
            transform=transform,
            defaults=defaults,
            filename_pattern=pattern,
        )


def _read_config(loader: _Loader, root: Path) -> BundleConfig:
    config_path = loader.root / CONFIG_FILENAME
    if not config_path.is_file():
        raise BundleConfigError([f"{CONFIG_FILENAME} not found in {root}"])
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BundleConfigError([f"{CONFIG_FILENAME} is not valid YAML: {exc}"]) from exc
    try:
        return BundleConfig.model_validate(raw)
    except ValidationError as exc:
        raise BundleConfigError(
            [
                f"{CONFIG_FILENAME}: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            ]
        ) from exc


def load_bundle(root: Path) -> Bundle:
    """Load and fully validate the bundle at ``root``.

    Raises :class:`BundleConfigError` listing every problem found, so a broken bundle
    is fixed in one pass rather than one restart per mistake.
    """
    loader = _Loader(root)
    if not loader.root.is_dir():
        raise BundleConfigError([f"bundle directory not found: {root}"])

    config = _read_config(loader, root)

    global_defaults: dict[str, Any] = {}
    if config.defaults is not None:
        global_defaults = loader.load_defaults(config.defaults, "defaults")

    templates: dict[str, LoadedTemplate] = {}
    for entry in config.templates:
        if entry.name in templates:
            loader.fail(f"template '{entry.name}': duplicate template name")
            continue
        loaded = loader.load_template(entry)
        if loaded is not None:
            templates[entry.name] = loaded

    if loader.problems:
        raise BundleConfigError(loader.problems)

    return Bundle(root=loader.root, global_defaults=global_defaults, templates=templates)
