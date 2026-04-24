"""HTTP tools layer — discovers tools from persona-configured services.

Per design decision D8 this package's ``__init__`` exports ONLY the
leaf-module symbols. Composite symbols such as ``discover_tools``
must be imported via their explicit module path
(``from assistant.http_tools.discovery import discover_tools``) so
the package remains importable at every intermediate state of the
work-package DAG.
"""

from assistant.http_tools.auth import AuthHeaderConfig, resolve_auth_header
from assistant.http_tools.registry import HttpToolRegistry

__all__ = [
    "AuthHeaderConfig",
    "HttpToolRegistry",
    "resolve_auth_header",
]
