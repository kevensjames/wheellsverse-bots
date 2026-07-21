"""AST-aware code chunking via tree-sitter.

The chunking STRATEGY (grammar→chunk-node types, size targets, character-splitter
fallback) is ported from zilliztech/claude-context (MIT reference), reimplemented
in Python against tree-sitter-language-pack. Chunks on top-level def/class/function
nodes for the supported languages; falls back to sliding-window chunking (reusing
services/rag.split_into_chunks) for unsupported languages or parse failures.
"""
from __future__ import annotations

import hashlib
import os

from app.services.code_intel.provider import CodeChunk

# file extension -> tree-sitter-language-pack language name
_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".h": "cpp",
    ".go": "go", ".rs": "rust", ".cs": "csharp", ".scala": "scala",
}

# Node types that make good standalone chunks (union across the supported grammars).
_CHUNK_NODE_TYPES = frozenset({
    "function_definition", "class_definition",                       # python
    "function_declaration", "method_definition", "class_declaration",  # js/ts
    "method_declaration", "constructor_declaration", "interface_declaration",  # java/c#
    "type_declaration", "func_declaration",                          # go
    "function_item", "impl_item", "struct_item", "enum_item", "trait_item", "mod_item",  # rust
    "object_definition", "trait_definition",                         # scala
    "namespace_definition", "struct_specifier", "class_specifier",   # cpp
})

# Wrapper nodes that hold a chunk-worthy node (export/decorator/ambient) — we
# emit the wrapper's text (so `export`/decorators are included) but take the
# symbol from the inner definition.
_WRAPPER_NODE_TYPES = frozenset({
    "export_statement", "export_default_declaration", "decorated_definition",
    "ambient_declaration",
})

_MAX_CHUNK_CHARS = 3000
_MIN_CHUNK_CHARS = 10


def lang_for(path: str) -> str | None:
    return _EXT_LANG.get(os.path.splitext(path)[1].lower())


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def _window_chunks(path: str, lang: str | None, source: str, line_offset: int = 0) -> list[CodeChunk]:
    """Sliding-window fallback with best-effort line numbers."""
    from app.services.rag import split_into_chunks

    out: list[CodeChunk] = []
    pos = 0
    for piece in split_into_chunks(source):
        idx = source.find(piece, pos)
        start = source.count("\n", 0, idx) + 1 + line_offset if idx >= 0 else 1 + line_offset
        end = start + piece.count("\n")
        pos = (idx + len(piece)) if idx >= 0 else pos
        out.append(CodeChunk(path=path, lang=lang or "text", symbol=None,
                             start_line=start, end_line=end,
                             content=piece, content_sha=_sha(piece)))
    return out


def chunk_file(path: str, source: str) -> list[CodeChunk]:
    lang = lang_for(path)
    if lang is None:
        return _window_chunks(path, None, source)
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(lang)
        tree = parser.parse(source.encode("utf-8", "replace"))
    except Exception:
        return _window_chunks(path, lang, source)

    src = source.encode("utf-8", "replace")

    def node_text(node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def symbol_of(node) -> str | None:
        n = node.child_by_field_name("name")
        return src[n.start_byte:n.end_byte].decode("utf-8", "replace") if n is not None else None

    out: list[CodeChunk] = []

    def emit(text_node, symbol_node) -> None:
        text = node_text(text_node)
        if len(text) <= _MAX_CHUNK_CHARS:
            if len(text.strip()) >= _MIN_CHUNK_CHARS:
                out.append(CodeChunk(path=path, lang=lang, symbol=symbol_of(symbol_node),
                                     start_line=text_node.start_point[0] + 1,
                                     end_line=text_node.end_point[0] + 1,
                                     content=text, content_sha=_sha(text)))
            return
        children = [c for c in symbol_node.children if c.type in _CHUNK_NODE_TYPES]
        if children:
            for c in children:
                emit(c, c)
        else:
            out.extend(_window_chunks(path, lang, text, line_offset=text_node.start_point[0]))

    def top_units(root):
        """Top-level chunk units as (text_node, symbol_node), unwrapping
        export/decorator wrappers."""
        units = []
        for c in root.children:
            if c.type in _CHUNK_NODE_TYPES:
                units.append((c, c))
            elif c.type in _WRAPPER_NODE_TYPES:
                inner = next((g for g in c.children if g.type in _CHUNK_NODE_TYPES), None)
                if inner is not None:
                    units.append((c, inner))  # text from wrapper, symbol from inner
        return units

    units = top_units(tree.root_node)
    if not units:
        # script-style file with no top-level defs -> window the whole file
        return _window_chunks(path, lang, source)
    for text_node, symbol_node in units:
        emit(text_node, symbol_node)
    return out
