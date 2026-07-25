"""
Tests for the AST parser — the foundation everything else builds on.
Run with: pytest tests/test_parser.py -v
"""
import pytest
from backend.parser.ast_parser import ASTParser
from backend.models import ParameterKind, TestCategory


@pytest.fixture
def parser():
    return ASTParser()


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------

def test_extracts_function_name(parser):
    result = parser.parse_source("def foo(x): return x")
    assert len(result.functions) == 1
    assert result.functions[0].name == "foo"


def test_extracts_multiple_functions(parser):
    src = "def foo(): pass\ndef bar(): pass\ndef baz(): pass"
    result = parser.parse_source(src)
    names = [f.name for f in result.functions]
    assert names == ["foo", "bar", "baz"]


def test_source_code_captured(parser):
    src = "def foo(x):\n    return x + 1\n"
    result = parser.parse_source(src)
    assert "def foo" in result.functions[0].source_code
    assert "return x + 1" in result.functions[0].source_code


def test_module_path_stored(parser):
    result = parser.parse_source("def foo(): pass", module_path="mymodule.py")
    assert result.functions[0].module_path == "mymodule.py"


def test_line_numbers_captured(parser):
    src = "def foo():\n    pass\n\ndef bar():\n    pass"
    result = parser.parse_source(src)
    assert result.functions[0].start_line == 1
    assert result.functions[1].start_line == 4


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def test_simple_parameters(parser):
    result = parser.parse_source("def add(a, b, c): return a + b + c")
    params = result.functions[0].parameters
    assert len(params) == 3
    assert [p.name for p in params] == ["a", "b", "c"]


def test_typed_parameters(parser):
    result = parser.parse_source("def greet(name: str, age: int) -> str: return name")
    params = result.functions[0].parameters
    assert params[0].type_hint == "str"
    assert params[1].type_hint == "int"


def test_return_type_hint(parser):
    result = parser.parse_source("def foo(x: int) -> float: return float(x)")
    assert result.functions[0].return_type_hint == "float"


def test_default_parameter(parser):
    result = parser.parse_source("def foo(x, y=10): return x + y")
    params = result.functions[0].parameters
    assert params[1].name == "y"
    assert params[1].kind == ParameterKind.KEYWORD
    assert params[1].default_value == "10"


def test_no_parameters(parser):
    result = parser.parse_source("def foo(): return 42")
    assert result.functions[0].parameters == []


def test_self_excluded_from_params(parser):
    src = "class Foo:\n    def bar(self, x): return x"
    result = parser.parse_source(src)
    params = result.functions[0].parameters
    assert all(p.name != "self" for p in params)
    assert len(params) == 1
    assert params[0].name == "x"


# ---------------------------------------------------------------------------
# Raises detection
# ---------------------------------------------------------------------------

def test_detects_raise(parser):
    src = """
def calculate_discount(price, discount_percent):
    if discount_percent > 100:
        raise ValueError("Discount can't exceed 100%")
    return price - (price * discount_percent / 100)
"""
    result = parser.parse_source(src)
    raises = result.functions[0].raises
    assert len(raises) == 1
    assert raises[0].exception_type == "ValueError"


def test_detects_multiple_raises(parser):
    src = """
def validate(x, y):
    if x < 0:
        raise ValueError("negative x")
    if y is None:
        raise TypeError("y cannot be None")
    return x + y
"""
    result = parser.parse_source(src)
    exc_types = [r.exception_type for r in result.functions[0].raises]
    assert "ValueError" in exc_types
    assert "TypeError" in exc_types


def test_no_raises(parser):
    result = parser.parse_source("def foo(x): return x * 2")
    assert result.functions[0].raises == []


# ---------------------------------------------------------------------------
# Call detection
# ---------------------------------------------------------------------------

def test_detects_function_calls(parser):
    src = """
def process(data):
    cleaned = clean_data(data)
    validated = validate_schema(cleaned)
    return transform(validated)
"""
    result = parser.parse_source(src)
    calls = result.functions[0].calls
    assert "clean_data" in calls
    assert "validate_schema" in calls
    assert "transform" in calls


def test_builtins_excluded_from_calls(parser):
    src = "def foo(items): return len(sorted(list(items)))"
    result = parser.parse_source(src)
    calls = result.functions[0].calls
    assert "len" not in calls
    assert "sorted" not in calls
    assert "list" not in calls


def test_no_calls(parser):
    result = parser.parse_source("def foo(x): return x + 1")
    assert result.functions[0].calls == []


# ---------------------------------------------------------------------------
# Control flow flags
# ---------------------------------------------------------------------------

def test_has_conditionals(parser):
    src = "def foo(x):\n    if x > 0:\n        return x\n    return -x"
    result = parser.parse_source(src)
    assert result.functions[0].has_conditionals is True


def test_has_loops(parser):
    src = "def foo(items):\n    for item in items:\n        print(item)"
    result = parser.parse_source(src)
    assert result.functions[0].has_loops is True


def test_no_control_flow(parser):
    result = parser.parse_source("def foo(x): return x * 2")
    fn = result.functions[0]
    assert fn.has_loops is False
    assert fn.has_conditionals is False


# ---------------------------------------------------------------------------
# Docstring
# ---------------------------------------------------------------------------

def test_extracts_docstring(parser):
    src = '''
def foo(x):
    """Multiplies x by two."""
    return x * 2
'''
    result = parser.parse_source(src)
    assert result.functions[0].docstring is not None
    assert "Multiplies" in result.functions[0].docstring


def test_no_docstring(parser):
    result = parser.parse_source("def foo(x): return x")
    assert result.functions[0].docstring is None


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def test_summary_format(parser):
    src = "def add(a: int, b: int) -> int: return a + b"
    result = parser.parse_source(src)
    summary = result.functions[0].summary()
    assert "add" in summary
    assert "int" in summary


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_source(parser):
    result = parser.parse_source("")
    assert result.functions == []


def test_only_comments(parser):
    result = parser.parse_source("# just a comment\n# nothing here")
    assert result.functions == []


def test_nested_function(parser):
    src = """
def outer(x):
    def inner(y):
        return y * 2
    return inner(x)
"""
    result = parser.parse_source(src)
    names = [f.name for f in result.functions]
    assert "outer" in names
    assert "inner" in names


def test_real_world_function(parser):
    src = """
def calculate_discount(price: float, discount_percent: float) -> float:
    \"\"\"Apply a percentage discount to a price.\"\"\"
    if discount_percent > 100:
        raise ValueError("Discount can't exceed 100%")
    if discount_percent < 0:
        raise ValueError("Discount can't be negative")
    return price - (price * discount_percent / 100)
"""
    result = parser.parse_source(src)
    assert len(result.functions) == 1
    fn = result.functions[0]
    assert fn.name == "calculate_discount"
    assert len(fn.parameters) == 2
    assert fn.parameters[0].type_hint == "float"
    assert fn.return_type_hint == "float"
    assert len(fn.raises) == 2
    assert fn.has_conditionals is True
    assert fn.docstring is not None