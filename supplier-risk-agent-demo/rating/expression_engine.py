"""受限表达式引擎：白名单 AST 解析 + 求值，非 eval 原始字符串。"""
from __future__ import annotations

import ast
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CMP_OPS = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "clamp": lambda v, lo, hi: max(lo, min(v, hi)),
    "sum": sum,
    "len": len,
    "contains": lambda container, item: (
        item in container if isinstance(container, (list, tuple, str)) else False
    ),
}


class ExpressionSecurityError(Exception):
    """表达式含非白名单节点。"""


class ExpressionSyntaxError(Exception):
    """表达式语法错误。"""


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
    ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Load, ast.Call,
    ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.UAdd, ast.USub,
    ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq,
)


def _validate_node(node: ast.AST) -> None:
    """递归校验 AST 节点，非白名单即拒绝。"""
    if not isinstance(node, _ALLOWED_NODES):
        raise ExpressionSecurityError(f"禁止节点: {type(node).__name__}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
            raise ExpressionSecurityError(f"禁止函数调用: {ast.dump(node.func)}")
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


def _eval_node(node: ast.AST, context: dict) -> object:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_eval_node(element, context) for element in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(element, context) for element in node.elts)
    if isinstance(node, ast.Name):
        if node.id in SAFE_FUNCTIONS:
            return SAFE_FUNCTIONS[node.id]
        if node.id in context:
            return context[node.id]
        raise ExpressionSecurityError(f"未定义字段: {node.id}")
    if isinstance(node, ast.BinOp):
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, context), _eval_node(node.right, context)
        )
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _eval_node(node.operand, context)
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, context))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comp in zip(node.ops, node.comparators):
            if not _CMP_OPS[type(op)](left, _eval_node(comp, context)):
                return False
            left = _eval_node(comp, context)
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, context) for v in node.values)
        return any(_eval_node(v, context) for v in node.values)
    if isinstance(node, ast.Call):
        func = SAFE_FUNCTIONS[node.func.id]
        args = [_eval_node(a, context) for a in node.args]
        return func(*args)
    raise ExpressionSecurityError(f"不可求值节点: {type(node).__name__}")


def evaluate_expression(expr: str, context: dict) -> object:
    """解析白名单 AST 并在受限命名空间求值。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        # Statements are never valid expressions. Distinguish explicitly
        # prohibited imports from ordinary malformed expressions so callers
        # can audit attempted namespace access as a security rejection.
        try:
            statement_tree = ast.parse(expr, mode="exec")
        except SyntaxError:
            statement_tree = None
        if statement_tree is not None and any(
            isinstance(node, (ast.Import, ast.ImportFrom))
            for node in ast.walk(statement_tree)
        ):
            raise ExpressionSecurityError("禁止导入模块") from exc
        raise ExpressionSyntaxError(str(exc)) from exc
    _validate_node(tree)
    return _eval_node(tree, context)
