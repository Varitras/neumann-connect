"""Cognitive Complexity (Campbell / SonarSource) for this package.

A measuring stick for the budget guard next door, not a general-purpose
implementation. Calibrated against SonarQube Cloud during the complexity
round of 1.18.1: Sonar reported 35 for `_read_lines_until_settled`, and this
scorer returns 35 for it.

Three rules:

  B1 increment  - if / elif / else, for, while, except, ternary, a SEQUENCE
                  of the same boolean operator, recursion
  B2 nesting    - if, for, while, except and ternary also add the current
                  nesting level; elif and else deliberately do not
  B3 nesting++  - branch, loop and handler bodies and nested definitions
                  raise the level

Cognitive rather than cyclomatic: a flat ten-case dispatch reads easily and
scores low, three loops inside each other do not. Only the second is what
made the read loop hard to change.
"""

import ast


class _Scorer(ast.NodeVisitor):
    """One function's score. Not reused across functions - the recursion rule
    needs to know which name counts as calling itself."""

    def __init__(self, function_name: str) -> None:
        self.score = 0
        self.nesting = 0
        self.function_name = function_name

    def _add(self, with_nesting: bool) -> None:
        self.score += 1 + (self.nesting if with_nesting else 0)

    def _deeper(self, nodes) -> None:
        self.nesting += 1
        for node in nodes:
            self.visit(node)
        self.nesting -= 1

    def visit_If(self, node: ast.If) -> None:
        self._add(with_nesting=True)
        self._deeper(node.body)
        orelse = node.orelse
        # An `elif` is a single If inside orelse: +1 without the nesting bonus,
        # and its body sits at the SAME level - a chain of elifs is a flat list
        # to read, not a staircase.
        while len(orelse) == 1 and isinstance(orelse[0], ast.If):
            inner = orelse[0]
            self._add(with_nesting=False)
            self.visit(inner.test)
            self._deeper(inner.body)
            orelse = inner.orelse
        if orelse:
            self._add(with_nesting=False)
            self._deeper(orelse)
        self.visit(node.test)

    def visit_For(self, node) -> None:
        self._add(with_nesting=True)
        self.visit(node.iter)
        self._deeper(node.body)
        if node.orelse:
            self._add(with_nesting=False)
            self._deeper(node.orelse)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self._add(with_nesting=True)
        self.visit(node.test)
        self._deeper(node.body)
        if node.orelse:
            self._add(with_nesting=False)
            self._deeper(node.orelse)

    def visit_Try(self, node) -> None:
        # The try body is free; only the handlers are a branch.
        for statement in node.body:
            self.visit(statement)
        for handler in node.handlers:
            self._add(with_nesting=True)
            self._deeper(handler.body)
        for statement in node.orelse + node.finalbody:
            self.visit(statement)

    visit_TryStar = visit_Try

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._add(with_nesting=True)
        self.visit(node.test)
        self._deeper([node.body, node.orelse])

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # One increment per SEQUENCE of the same operator: `a and b and c` is
        # one thought, `a and b or c` is two.
        self._add(with_nesting=False)
        for value in node.values:
            self.visit(value)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == self.function_name:
            self._add(with_nesting=False)
        self.generic_visit(node)

    def visit_FunctionDef(self, node) -> None:
        self._deeper(node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._deeper([node.body])


def score(node) -> int:
    """The cognitive complexity of one function definition."""
    scorer = _Scorer(node.name)
    for statement in node.body:
        scorer.visit(statement)
    return scorer.score


def functions(tree, prefix: str = ""):
    """Every top-level and method definition, as (qualified name, node).

    Nested definitions are not yielded separately - they are scored inside the
    function containing them, which is where their cost is felt.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield prefix + node.name, node
        elif isinstance(node, ast.ClassDef):
            yield from functions(node, prefix + node.name + ".")
