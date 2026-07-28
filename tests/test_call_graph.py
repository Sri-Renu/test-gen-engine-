"""
Tests for the call graph builder.
Run with: pytest tests/test_call_graph.py -v
"""
import pytest
from backend.parser.ast_parser import ASTParser
from backend.parser.call_graph import CallGraphBuilder


@pytest.fixture
def parser():
    return ASTParser()


@pytest.fixture
def builder():
    return CallGraphBuilder()


def test_builds_from_parse_result(parser, builder):
    src = "def foo(): pass\ndef bar(): pass"
    result = parser.parse_source(src)
    builder.build(result)
    assert "foo" in builder.get_all_function_names()
    assert "bar" in builder.get_all_function_names()


def test_call_edges_recorded(parser, builder):
    src = """
def apply_tax(price): return price * 1.1
def calculate_discount(price, pct):
    return apply_tax(price - price * pct / 100)
"""
    result = parser.parse_source(src)
    builder.build(result)
    deps = builder.get_dependencies("calculate_discount", depth=1)
    dep_names = [d.name for d in deps]
    assert "apply_tax" in dep_names


def test_depth_limiting(parser, builder):
    src = """
def a(): return b()
def b(): return c()
def c(): return 1
"""
    result = parser.parse_source(src)
    builder.build(result)

    deps_depth1 = builder.get_dependencies("a", depth=1)
    assert len(deps_depth1) == 1
    assert deps_depth1[0].name == "b"

    deps_depth2 = builder.get_dependencies("a", depth=2)
    dep_names = [d.name for d in deps_depth2]
    assert "b" in dep_names
    assert "c" in dep_names


def test_get_callers(parser, builder):
    src = """
def helper(): return 1
def foo(): return helper()
def bar(): return helper()
"""
    result = parser.parse_source(src)
    builder.build(result)
    callers = builder.get_callers("helper")
    caller_names = [c.name for c in callers]
    assert "foo" in caller_names
    assert "bar" in caller_names


def test_unknown_function_returns_empty(builder):
    assert builder.get_dependencies("nonexistent") == []


def test_summary_format(parser, builder):
    src = """
def foo(): pass
def bar(): return foo()
"""
    result = parser.parse_source(src)
    builder.build(result)
    summary = builder.summary()
    assert "2" in summary  # 2 functions


def test_to_dict_serializable(parser, builder):
    src = """
def foo(): pass
def bar(): return foo()
"""
    result = parser.parse_source(src)
    builder.build(result)
    d = builder.to_dict()
    assert "nodes" in d
    assert "edges" in d
    assert isinstance(d["nodes"], list)
    assert isinstance(d["edges"], list)


def test_multi_file_merge(parser, builder):
    src1 = "def foo(): pass"
    src2 = "def bar(): return foo()"
    r1 = parser.parse_source(src1, "file1.py")
    r2 = parser.parse_source(src2, "file2.py")
    builder.build_from_sources([r1, r2])
    assert builder.has_function("foo")
    assert builder.has_function("bar")