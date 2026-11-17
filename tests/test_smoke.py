import tree_sitter_python
from tree_sitter import Language, Parser

import deferred_imports


def test_package_imports():
    assert deferred_imports.__version__


def test_tree_sitter_parses_an_import():
    parser = Parser(Language(tree_sitter_python.language()))
    tree = parser.parse(b"import os\n")
    assert tree.root_node.children[0].type == "import_statement"
