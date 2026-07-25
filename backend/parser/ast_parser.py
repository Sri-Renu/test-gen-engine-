"""
AST Parser — Stage 1 of the pipeline.

Uses Tree-sitter to parse Python source code and extract structured
FunctionInfo objects. Works on raw strings (pasted code) or file paths.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

from backend.models import (
    FunctionInfo, Parameter, ParameterKind, ParseResult, RaisedError
)

PY_LANGUAGE = Language(tspython.language())


class ASTParser:
    """
    Parse Python source code into structured FunctionInfo objects.

    Usage:
        parser = ASTParser()
        result = parser.parse_source(source_code, module_path="snippet")
        for fn in result.functions:
            print(fn.summary())
    """

    def __init__(self):
        self._parser = Parser(PY_LANGUAGE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_source(self, source: str, module_path: str = "<snippet>") -> ParseResult:
        """Parse a raw Python source string."""
        source_bytes = source.encode("utf-8")
        tree = self._parser.parse(source_bytes)
        return self._extract(tree.root_node, source_bytes, module_path)

    def parse_file(self, path: str | Path) -> ParseResult:
        """Parse a Python file from disk."""
        path = Path(path)
        source = path.read_text(encoding="utf-8")
        return self.parse_source(source, module_path=str(path))

    # ------------------------------------------------------------------
    # Internal extraction
    # ------------------------------------------------------------------

    def _extract(self, root: Node, source_bytes: bytes, module_path: str) -> ParseResult:
        result = ParseResult()
        errors = self._collect_errors(root)
        if errors:
            result.parse_errors = errors

        fn_nodes = self._collect_function_nodes(root)
        for node in fn_nodes:
            try:
                fn_info = self._build_function_info(node, source_bytes, module_path)
                result.functions.append(fn_info)
            except Exception as e:
                result.parse_errors.append(f"Failed to parse function node: {e}")

        return result

    def _collect_function_nodes(self, root: Node) -> list[Node]:
        """Walk the tree and collect all function_definition nodes."""
        nodes = []
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "function_definition":
                nodes.append(node)
            stack.extend(reversed(node.children))
        return nodes

    def _build_function_info(
        self, node: Node, source_bytes: bytes, module_path: str
    ) -> FunctionInfo:
        name = self._get_child_text(node, "identifier", source_bytes)
        source_code = source_bytes[node.start_byte:node.end_byte].decode("utf-8")

        parameters = self._extract_parameters(node, source_bytes)
        return_type_hint = self._extract_return_type(node, source_bytes)
        docstring = self._extract_docstring(node, source_bytes)
        raises = self._extract_raises(node, source_bytes)
        calls = self._extract_calls(node, source_bytes)
        has_loops = self._has_node_type(node, {"for_statement", "while_statement"})
        has_conditionals = self._has_node_type(node, {"if_statement"})

        return FunctionInfo(
            name=name,
            module_path=module_path,
            source_code=source_code,
            parameters=parameters,
            return_type_hint=return_type_hint,
            raises=raises,
            calls=calls,
            has_loops=has_loops,
            has_conditionals=has_conditionals,
            docstring=docstring,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _extract_parameters(self, fn_node: Node, source_bytes: bytes) -> list[Parameter]:
        params = []
        param_node = self._find_child(fn_node, "parameters")
        if not param_node:
            return params

        for child in param_node.children:
            if child.type == "identifier":
                params.append(Parameter(
                    name=self._node_text(child, source_bytes),
                    kind=ParameterKind.POSITIONAL,
                ))
            elif child.type == "typed_parameter":
                param = self._parse_typed_parameter(child, source_bytes)
                if param:
                    params.append(param)
            elif child.type == "default_parameter":
                param = self._parse_default_parameter(child, source_bytes)
                if param:
                    params.append(param)
            elif child.type == "typed_default_parameter":
                param = self._parse_typed_default_parameter(child, source_bytes)
                if param:
                    params.append(param)
            elif child.type == "list_splat_pattern":
                # *args
                inner = self._find_child(child, "identifier")
                if inner:
                    params.append(Parameter(
                        name=self._node_text(inner, source_bytes),
                        kind=ParameterKind.VAR_POSITIONAL,
                    ))
            elif child.type == "dictionary_splat_pattern":
                # **kwargs
                inner = self._find_child(child, "identifier")
                if inner:
                    params.append(Parameter(
                        name=self._node_text(inner, source_bytes),
                        kind=ParameterKind.VAR_KEYWORD,
                    ))

        # Skip 'self' / 'cls' in methods
        params = [p for p in params if p.name not in ("self", "cls")]
        return params

    def _parse_typed_parameter(self, node: Node, source_bytes: bytes) -> Optional[Parameter]:
        name_node = self._find_child(node, "identifier")
        type_node = self._find_child(node, "type")
        if not name_node:
            return None
        return Parameter(
            name=self._node_text(name_node, source_bytes),
            kind=ParameterKind.POSITIONAL,
            type_hint=self._node_text(type_node, source_bytes) if type_node else None,
        )

    def _parse_default_parameter(self, node: Node, source_bytes: bytes) -> Optional[Parameter]:
        children = [c for c in node.children if c.type not in ("=", ",")]
        if len(children) < 2:
            return None
        return Parameter(
            name=self._node_text(children[0], source_bytes),
            kind=ParameterKind.KEYWORD,
            default_value=self._node_text(children[1], source_bytes),
        )

    def _parse_typed_default_parameter(self, node: Node, source_bytes: bytes) -> Optional[Parameter]:
        name_node = self._find_child(node, "identifier")
        type_node = self._find_child(node, "type")
        # default is after '='
        default_node = None
        found_eq = False
        for child in node.children:
            if child.type == "=":
                found_eq = True
                continue
            if found_eq and child.type not in (",",):
                default_node = child
                break
        if not name_node:
            return None
        return Parameter(
            name=self._node_text(name_node, source_bytes),
            kind=ParameterKind.KEYWORD,
            type_hint=self._node_text(type_node, source_bytes) if type_node else None,
            default_value=self._node_text(default_node, source_bytes) if default_node else None,
        )

    def _extract_return_type(self, fn_node: Node, source_bytes: bytes) -> Optional[str]:
        type_node = self._find_child(fn_node, "type")
        if type_node:
            return self._node_text(type_node, source_bytes)
        return None

    def _extract_docstring(self, fn_node: Node, source_bytes: bytes) -> Optional[str]:
        body = self._find_child(fn_node, "block")
        if not body:
            return None
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        raw = self._node_text(sub, source_bytes)
                        return raw.strip('"\' \t\n').strip('"""').strip("'''").strip()
        return None

    def _extract_raises(self, fn_node: Node, source_bytes: bytes) -> list[RaisedError]:
        raises = []
        stack = [fn_node]
        while stack:
            node = stack.pop()
            if node.type == "raise_statement":
                exc_node = None
                for child in node.children:
                    if child.type in ("call", "identifier"):
                        exc_node = child
                        break
                if exc_node:
                    exc_text = self._node_text(exc_node, source_bytes)
                    # Extract just the exception type name (before the '(')
                    exc_type = exc_text.split("(")[0].strip()
                    snippet = source_bytes[node.start_byte:node.end_byte].decode("utf-8")
                    raises.append(RaisedError(
                        exception_type=exc_type,
                        condition_snippet=snippet,
                    ))
            stack.extend(reversed(node.children))
        return raises

    def _extract_calls(self, fn_node: Node, source_bytes: bytes) -> list[str]:
        calls = set()
        stack = [fn_node]
        while stack:
            node = stack.pop()
            if node.type == "call":
                func = self._find_child(node, "identifier")
                if func:
                    calls.add(self._node_text(func, source_bytes))
                # attribute call: obj.method()
                attr = self._find_child(node, "attribute")
                if attr:
                    attr_name = self._find_child(attr, "identifier")
                    if attr_name:
                        calls.add(self._node_text(attr_name, source_bytes))
            stack.extend(reversed(node.children))
        # Remove Python builtins and ALL exception classes.
        # Exception types appear as calls in raise statements:
        #   raise ValueError(...)  →  tree-sitter sees ValueError() as a call
        # This would pollute the call graph with noise the agent doesn't need.
        builtins = {
            # Functions
            "print", "len", "range", "int", "str", "float", "list",
            "dict", "set", "tuple", "bool", "type", "isinstance",
            "hasattr", "getattr", "setattr", "super", "zip", "map",
            "filter", "sorted", "enumerate", "open", "round", "abs",
            "min", "max", "sum", "any", "all", "repr", "id", "hash",
            "iter", "next", "reversed", "vars", "dir", "callable",
            "staticmethod", "classmethod", "property",
            # Exception classes (appear as calls inside raise statements)
            "Exception", "BaseException", "ValueError", "TypeError",
            "KeyError", "IndexError", "AttributeError", "RuntimeError",
            "OSError", "IOError", "FileNotFoundError", "PermissionError",
            "NotImplementedError", "StopIteration", "GeneratorExit",
            "ArithmeticError", "ZeroDivisionError", "OverflowError",
            "MemoryError", "RecursionError", "SystemError", "SystemExit",
            "ImportError", "ModuleNotFoundError", "NameError",
            "UnboundLocalError", "LookupError", "AssertionError",
            "UnicodeError", "UnicodeDecodeError", "UnicodeEncodeError",
            "BufferError", "EOFError", "ConnectionError", "TimeoutError",
            "Warning", "UserWarning", "DeprecationWarning",
        }
        return sorted(calls - builtins)

    def _has_node_type(self, root: Node, types: set[str]) -> bool:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in types:
                return True
            stack.extend(reversed(node.children))
        return False

    def _collect_errors(self, root: Node) -> list[str]:
        errors = []
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "ERROR":
                errors.append(f"Parse error at line {node.start_point[0] + 1}")
            stack.extend(reversed(node.children))
        return errors

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _find_child(self, node: Node, child_type: str) -> Optional[Node]:
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _node_text(self, node: Node, source_bytes: bytes) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8")

    def _get_child_text(self, node: Node, child_type: str, source_bytes: bytes) -> str:
        child = self._find_child(node, child_type)
        if child:
            return self._node_text(child, source_bytes)
        return ""