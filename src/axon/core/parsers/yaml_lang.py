"""YAML parser for infrastructure/config files.

This parser is intentionally lightweight and line-based:
- Detects YAML documents split by ``---``.
- Extracts resource-like symbols using ``kind`` + ``metadata.name`` when present.
- Falls back to top-level keys for non-Kubernetes YAML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from axon.core.parsers.base import LanguageParser, ParseResult, SymbolInfo

_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$")
_INLINE_NAME_RE = re.compile(r"\bname\s*:\s*([^,}]+)")


@dataclass(frozen=True)
class _Document:
    start_line: int
    end_line: int
    lines: list[str]


class YamlParser(LanguageParser):
    """Parses YAML manifests into document-level symbols."""

    def parse(self, content: str, file_path: str) -> ParseResult:
        del file_path  # line-based parser does not currently use file path.
        result = ParseResult()
        lines = content.splitlines()
        if not lines:
            return result

        documents = self._split_documents(lines)
        for index, document in enumerate(documents, start=1):
            symbol = self._build_document_symbol(document, index)
            if symbol is not None:
                result.symbols.append(symbol)
        return result

    def _split_documents(self, lines: list[str]) -> list[_Document]:
        documents: list[_Document] = []
        start_line = 1

        for line_no, raw in enumerate(lines, start=1):
            if raw.strip() != "---":
                continue

            if line_no > start_line:
                doc_lines = lines[start_line - 1 : line_no - 1]
                documents.append(
                    _Document(start_line=start_line, end_line=line_no - 1, lines=doc_lines)
                )
            start_line = line_no + 1

        if start_line <= len(lines):
            doc_lines = lines[start_line - 1 :]
            documents.append(
                _Document(start_line=start_line, end_line=len(lines), lines=doc_lines)
            )

        return documents

    def _build_document_symbol(self, document: _Document, index: int) -> SymbolInfo | None:
        kind = ""
        metadata_name = ""
        top_level_keys: list[str] = []
        in_metadata = False
        metadata_indent = 0

        for raw in document.lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(raw) - len(raw.lstrip(" "))
            key_match = _TOP_LEVEL_KEY_RE.match(raw.lstrip(" "))
            if key_match is None:
                continue

            key = key_match.group(1)
            value = key_match.group(2).strip()

            if indent == 0:
                in_metadata = key == "metadata"
                metadata_indent = indent if in_metadata else 0

                if key not in top_level_keys:
                    top_level_keys.append(key)

                if key == "kind" and value:
                    kind = value.strip("\"'")

                if key == "metadata" and value and not metadata_name:
                    inline = _INLINE_NAME_RE.search(value)
                    if inline is not None:
                        metadata_name = inline.group(1).strip().strip("\"'")
                continue

            if (
                in_metadata
                and indent > metadata_indent
                and key == "name"
                and value
                and not metadata_name
            ):
                metadata_name = value.strip("\"'")

        symbol_kind = "class" if kind else "type_alias"
        symbol_name = self._build_symbol_name(kind, metadata_name, top_level_keys, index)

        if not symbol_name:
            return None

        signature = kind
        if kind and metadata_name:
            signature = f"{kind} {metadata_name}"
        elif not kind:
            signature = f"yaml {symbol_name}"

        return SymbolInfo(
            name=symbol_name,
            kind=symbol_kind,
            start_line=document.start_line,
            end_line=document.end_line,
            content="\n".join(document.lines),
            signature=signature,
        )

    @staticmethod
    def _build_symbol_name(
        kind: str,
        metadata_name: str,
        top_level_keys: list[str],
        index: int,
    ) -> str:
        if kind and metadata_name:
            return f"{kind}/{metadata_name}"
        if kind:
            return kind
        if metadata_name:
            return metadata_name
        if top_level_keys:
            return f"document_{index}:{top_level_keys[0]}"
        return f"document_{index}"
