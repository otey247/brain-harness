"""A PyYAML loader restricted to the YAML 1.2 core schema.

OKF (SPEC §4.1) requires YAML 1.2 core. PyYAML implements YAML 1.1, where
``yes``/``no``/``on``/``off`` become booleans and ``010`` becomes octal. This
loader keeps only the 1.2 core implicit resolvers so values such as
``status: on`` or ``id: 010`` stay strings, and refuses custom tags.
"""

from __future__ import annotations

import re
from typing import Any

import yaml


class Yaml12Error(ValueError):
    """Raised when frontmatter is not a valid YAML 1.2 core mapping."""


class _Core12Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 core-schema scalar resolution and no duplicate keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
            if key in seen:
                raise Yaml12Error(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# Reset the implicit resolvers inherited from PyYAML's 1.1 schema.
_Core12Loader.yaml_implicit_resolvers = {}

_Core12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:null",
    re.compile(r"^(?:~|null|Null|NULL|)$"),
    ["~", "n", "N", ""],
)
_Core12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
_Core12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"),
    list("-+0123456789"),
)
_Core12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
        r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
    ),
    list("-+0123456789."),
)


def _construct_int(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> int:
    value = loader.construct_scalar(node)
    text = str(value)
    if text.startswith("0o"):
        return int(text[2:], 8)
    if text.startswith("0x"):
        return int(text[2:], 16)
    return int(text, 10)


_Core12Loader.add_constructor("tag:yaml.org,2002:int", _construct_int)


def _reject_unknown_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> Any:
    raise Yaml12Error(f"custom YAML tags are not allowed (found !{tag_suffix})")


_Core12Loader.add_multi_constructor("!", _reject_unknown_tag)


def load_mapping(text: str) -> dict[str, Any]:
    """Parse ``text`` as a YAML 1.2 core document that must be a mapping.

    An empty document returns an empty mapping.
    """
    try:
        data = yaml.load(text, Loader=_Core12Loader)
    except Yaml12Error:
        raise
    except yaml.YAMLError as exc:
        raise Yaml12Error(str(exc)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise Yaml12Error(f"frontmatter must be a mapping, got {type(data).__name__}")
    return data
