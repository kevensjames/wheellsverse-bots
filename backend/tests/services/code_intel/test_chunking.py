"""AST chunking: def/class boundaries with correct line numbers; fallback for
unsupported languages; no crash on malformed input."""
from app.services.code_intel.chunking import chunk_file, lang_for


def test_python_chunks_on_def_and_class_with_lines():
    src = (
        "import os\n"              # line 1
        "\n"
        "def alpha(x):\n"          # line 3
        "    return x + 1\n"       # line 4
        "\n"
        "class Beta:\n"            # line 6
        "    def m(self):\n"       # line 7
        "        return 2\n"       # line 8
    )
    chunks = chunk_file("mod.py", src)
    by_symbol = {c.symbol: c for c in chunks}
    assert "alpha" in by_symbol and "Beta" in by_symbol
    alpha = by_symbol["alpha"]
    assert alpha.lang == "python"
    assert alpha.start_line == 3 and alpha.end_line == 4
    beta = by_symbol["Beta"]
    assert beta.start_line == 6 and beta.end_line == 8
    assert all(c.content_sha for c in chunks)


def test_typescript_chunks_on_function_and_class():
    src = (
        "export function greet(n: string): string {\n"
        "  return `hi ${n}`;\n"
        "}\n"
        "\n"
        "class Widget {\n"
        "  render() { return 1; }\n"
        "}\n"
    )
    chunks = chunk_file("app.ts", src)
    syms = {c.symbol for c in chunks}
    assert "greet" in syms and "Widget" in syms
    assert all(c.lang == "typescript" for c in chunks)


def test_unsupported_language_falls_back_without_error():
    src = "some plain prose\n" * 100
    chunks = chunk_file("notes.txt", src)
    assert lang_for("notes.txt") is None
    assert len(chunks) >= 1
    assert all(c.symbol is None and c.lang == "text" for c in chunks)


def test_script_style_python_without_defs_falls_back():
    src = "x = 1\nprint(x)\ny = x + 2\nprint(y)\n"
    chunks = chunk_file("script.py", src)
    assert len(chunks) >= 1  # windowed, not empty


def test_malformed_source_does_not_crash():
    chunks = chunk_file("broken.py", "def (:\n  ??? not valid python\n")
    assert isinstance(chunks, list)  # tree-sitter is error-tolerant; never raises
