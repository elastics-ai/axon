"""Go parser using tree-sitter.

Extracts functions, methods, type declarations, imports, calls, and type
references from Go source code.
"""

from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from axon.core.parsers.base import (
    CallInfo,
    ImportInfo,
    LanguageParser,
    ParseResult,
    SymbolInfo,
    TypeRef,
)

GO_LANGUAGE = Language(tsgo.language())

_GO_BUILTIN_TYPES: frozenset[str] = frozenset(
    {
        "any",
        "bool",
        "byte",
        "comparable",
        "complex64",
        "complex128",
        "error",
        "float32",
        "float64",
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "rune",
        "string",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
    }
)


class GoParser(LanguageParser):
    """Parses Go source code using tree-sitter."""

    def __init__(self) -> None:
        self._parser = Parser(GO_LANGUAGE)

    def parse(self, content: str, file_path: str) -> ParseResult:
        """Parse Go source and return structured information."""
        tree = self._parser.parse(content.encode("utf-8"))
        result = ParseResult()
        self._walk(tree.root_node, result)
        return result

    def _walk(self, node: Node, result: ParseResult) -> None:
        """Recursively walk the AST and extract parse artifacts."""
        if node.type == "function_declaration":
            self._extract_function(node, result)
        elif node.type == "method_declaration":
            self._extract_method(node, result)
        elif node.type == "type_declaration":
            self._extract_type_declaration(node, result)
        elif node.type == "import_declaration":
            self._extract_import_declaration(node, result)
        elif node.type == "call_expression":
            self._extract_call(node, result)
        elif node.type == "var_declaration":
            self._extract_var_declaration(node, result)

        for child in node.children:
            self._walk(child, result)

    def _extract_function(self, node: Node, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = name_node.text.decode("utf-8")
        symbol = SymbolInfo(
            name=name,
            kind="function",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=node.text.decode("utf-8"),
            signature=self._build_signature(node),
        )
        result.symbols.append(symbol)
        self._append_export_if_public(name, result)

        params = node.child_by_field_name("parameters")
        if params is not None:
            self._extract_param_types(params, result, kind="param")

        returns = node.child_by_field_name("result")
        if returns is not None:
            self._extract_result_types(returns, result)

    def _extract_method(self, node: Node, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        receiver = node.child_by_field_name("receiver")
        receiver_type, _ = self._extract_receiver_info(receiver)

        name = name_node.text.decode("utf-8")
        symbol = SymbolInfo(
            name=name,
            kind="method",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=node.text.decode("utf-8"),
            signature=self._build_signature(node),
            class_name=receiver_type,
        )
        result.symbols.append(symbol)
        self._append_export_if_public(name, result)

        params = node.child_by_field_name("parameters")
        if params is not None:
            self._extract_param_types(params, result, kind="param")

        returns = node.child_by_field_name("result")
        if returns is not None:
            self._extract_result_types(returns, result)

    def _extract_type_declaration(self, node: Node, result: ParseResult) -> None:
        for spec in self._iter_type_specs(node):
            if spec.type == "type_alias":
                self._extract_type_alias(spec, result)
            elif spec.type == "type_spec":
                self._extract_type_spec(spec, result)

    def _extract_type_alias(self, node: Node, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = name_node.text.decode("utf-8")
        result.symbols.append(
            SymbolInfo(
                name=name,
                kind="type_alias",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                content=node.text.decode("utf-8"),
                signature=f"type {node.text.decode('utf-8').strip()}",
            )
        )
        self._append_export_if_public(name, result)

        type_node = node.child_by_field_name("type")
        if type_node is not None:
            self._add_type_ref(
                type_node=type_node,
                kind="variable",
                line=type_node.start_point[0] + 1,
                result=result,
            )

    def _extract_type_spec(self, node: Node, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        type_node = node.child_by_field_name("type")
        if name_node is None or type_node is None:
            return

        name = name_node.text.decode("utf-8")
        if type_node.type == "struct_type":
            kind = "class"
        elif type_node.type == "interface_type":
            kind = "interface"
        else:
            kind = "type_alias"

        result.symbols.append(
            SymbolInfo(
                name=name,
                kind=kind,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                content=node.text.decode("utf-8"),
                signature=f"type {node.text.decode('utf-8').strip()}",
            )
        )
        self._append_export_if_public(name, result)

        if type_node.type == "struct_type":
            self._extract_struct_field_types(type_node, result)
        elif type_node.type == "interface_type":
            self._extract_interface_types(type_node, result)
        else:
            self._add_type_ref(
                type_node=type_node,
                kind="variable",
                line=type_node.start_point[0] + 1,
                result=result,
            )

    def _extract_import_declaration(self, node: Node, result: ParseResult) -> None:
        for spec in self._iter_import_specs(node):
            path_node = spec.child_by_field_name("path")
            if path_node is None:
                continue

            module = self._strip_quoted(path_node.text.decode("utf-8"))
            if not module:
                continue

            alias_node = spec.child_by_field_name("name")
            alias = ""
            names: list[str] = []
            if alias_node is not None:
                alias_value = alias_node.text.decode("utf-8")
                if alias_value not in (".", "_"):
                    alias = alias_value
                    names = [alias_value]

            result.imports.append(
                ImportInfo(
                    module=module,
                    names=names,
                    is_relative=module.startswith("."),
                    alias=alias,
                )
            )

    def _extract_call(self, node: Node, result: ParseResult) -> None:
        function_node = node.child_by_field_name("function")
        if function_node is None:
            return

        name = ""
        receiver = ""

        if function_node.type == "identifier":
            name = function_node.text.decode("utf-8")
        elif function_node.type == "selector_expression":
            field = function_node.child_by_field_name("field")
            operand = function_node.child_by_field_name("operand")
            if field is not None:
                name = field.text.decode("utf-8")
            if operand is not None:
                receiver = operand.text.decode("utf-8")
        else:
            return

        if not name:
            return

        arguments: list[str] = []
        args_node = node.child_by_field_name("arguments")
        if args_node is not None:
            for child in args_node.children:
                if child.type == "identifier":
                    arguments.append(child.text.decode("utf-8"))

        result.calls.append(
            CallInfo(
                name=name,
                line=node.start_point[0] + 1,
                receiver=receiver,
                arguments=arguments,
            )
        )

    def _extract_var_declaration(self, node: Node, result: ParseResult) -> None:
        for child in node.children:
            if child.type != "var_spec":
                continue
            type_node = child.child_by_field_name("type")
            if type_node is None:
                continue
            param_name = ""
            for name_node in child.children:
                if name_node.type == "identifier":
                    param_name = name_node.text.decode("utf-8")
                    break
            self._add_type_ref(
                type_node=type_node,
                kind="variable",
                line=type_node.start_point[0] + 1,
                result=result,
                param_name=param_name,
            )

    def _extract_param_types(
        self,
        params_node: Node,
        result: ParseResult,
        kind: str,
    ) -> None:
        for param in params_node.children:
            if param.type != "parameter_declaration":
                continue

            type_node = param.child_by_field_name("type")
            if type_node is None:
                continue

            param_name = ""
            for child in param.children:
                if child.type == "identifier":
                    param_name = child.text.decode("utf-8")
                    break

            self._add_type_ref(
                type_node=type_node,
                kind=kind,
                line=type_node.start_point[0] + 1,
                result=result,
                param_name=param_name if kind == "param" else "",
            )

    def _extract_result_types(self, result_node: Node, result: ParseResult) -> None:
        if result_node.type == "parameter_list":
            self._extract_param_types(result_node, result, kind="return")
            return

        self._add_type_ref(
            type_node=result_node,
            kind="return",
            line=result_node.start_point[0] + 1,
            result=result,
        )

    def _extract_struct_field_types(self, struct_node: Node, result: ParseResult) -> None:
        for field in self._iter_nodes(struct_node, {"field_declaration"}):
            type_node = field.child_by_field_name("type")
            if type_node is None:
                for child in field.children:
                    if child.type in ("type_identifier", "qualified_type"):
                        type_node = child
                        break
            if type_node is None:
                continue
            self._add_type_ref(
                type_node=type_node,
                kind="variable",
                line=type_node.start_point[0] + 1,
                result=result,
            )

    def _extract_interface_types(self, interface_node: Node, result: ParseResult) -> None:
        for child in interface_node.children:
            if child.type == "method_elem":
                params = child.child_by_field_name("parameters")
                returns = child.child_by_field_name("result")
                if params is not None:
                    self._extract_param_types(params, result, kind="param")
                if returns is not None:
                    self._extract_result_types(returns, result)
            elif child.type == "type_elem":
                for elem_child in child.children:
                    if elem_child.type in ("type_identifier", "qualified_type", "generic_type"):
                        self._add_type_ref(
                            type_node=elem_child,
                            kind="variable",
                            line=elem_child.start_point[0] + 1,
                            result=result,
                        )

    def _extract_receiver_info(self, receiver_node: Node | None) -> tuple[str, str]:
        if receiver_node is None:
            return "", ""

        for child in receiver_node.children:
            if child.type != "parameter_declaration":
                continue
            type_node = child.child_by_field_name("type")
            receiver_type = (
                self._extract_primary_type_name(type_node)
                if type_node is not None
                else ""
            )

            receiver_name = ""
            for name_node in child.children:
                if name_node.type == "identifier":
                    receiver_name = name_node.text.decode("utf-8")
                    break

            return receiver_type, receiver_name

        return "", ""

    def _add_type_ref(
        self,
        type_node: Node,
        kind: str,
        line: int,
        result: ParseResult,
        param_name: str = "",
    ) -> None:
        type_name = self._extract_primary_type_name(type_node)
        if not type_name or type_name in _GO_BUILTIN_TYPES:
            return
        result.type_refs.append(
            TypeRef(
                name=type_name,
                kind=kind,
                line=line,
                param_name=param_name,
            )
        )

    def _extract_primary_type_name(self, type_node: Node | None) -> str:
        if type_node is None:
            return ""
        for name in self._collect_type_names(type_node):
            if name and name not in _GO_BUILTIN_TYPES:
                return name
        return ""

    def _collect_type_names(self, node: Node) -> list[str]:
        names: list[str] = []

        if node.type == "type_identifier":
            names.append(node.text.decode("utf-8"))
        elif node.type == "qualified_type":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                names.append(name_node.text.decode("utf-8"))
            else:
                names.append(node.text.decode("utf-8").split(".")[-1])

        for child in node.children:
            names.extend(self._collect_type_names(child))

        return names

    def _append_export_if_public(self, name: str, result: ParseResult) -> None:
        if name and name[0].isupper() and name not in result.exports:
            result.exports.append(name)

    def _build_signature(self, node: Node) -> str:
        text = node.text.decode("utf-8").strip()
        head = text.split("{", 1)[0].strip()
        return head

    def _iter_type_specs(self, type_decl: Node) -> list[Node]:
        specs: list[Node] = []
        for child in type_decl.children:
            if child.type in ("type_spec", "type_alias"):
                specs.append(child)
            elif child.type == "type_spec_list":
                for spec in child.children:
                    if spec.type in ("type_spec", "type_alias"):
                        specs.append(spec)
        return specs

    def _iter_import_specs(self, import_decl: Node) -> list[Node]:
        specs: list[Node] = []
        for child in import_decl.children:
            if child.type == "import_spec":
                specs.append(child)
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        specs.append(spec)
        return specs

    def _iter_nodes(self, node: Node, target_types: set[str]) -> list[Node]:
        found: list[Node] = []
        for child in node.children:
            if child.type in target_types:
                found.append(child)
            found.extend(self._iter_nodes(child, target_types))
        return found

    @staticmethod
    def _strip_quoted(value: str) -> str:
        text = value.strip()
        if (text.startswith('"') and text.endswith('"')) or (
            text.startswith("`") and text.endswith("`")
        ):
            return text[1:-1]
        return text
