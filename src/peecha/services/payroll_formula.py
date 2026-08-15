"""زبانِ محدودِ فرمولِ آیتمِ حقوقی (Pay Item Formula DSL) — فصلِ ۶ از سندِ
طراحی: «عبارتِ کاربر هرگز با eval() اجرا نمی‌شود». این فایل یک
tokenizer/parser/evaluator کاملاً دستی (بدونِ ast.literal_eval یا eval
پایتون) برایِ زیرمجموعه‌ای بسیار محدود از عبارات ریاضی می‌سازد:

    + - * / ( )                  عملگرها
    اعداد                        ثابت
    BASE_SALARY, WORKED_DAYS,
    CALENDAR_DAYS, CHILDREN_COUNT,
    WEEKLY_HOURS                 متغیرهایِ مجاز
    {ITEM_CODE}                  ارجاع به مقدارِ محاسبه‌شدهٔ آیتمِ دیگر
    POLICY(CODE)                 مقدارِ جاریِ یک قانونِ حقوقی (فصلِ ۷)

پیش از اجرا: پارس با گرامرِ whitelist، ساختِ گراف‌وابستگی از ارجاع‌هایِ
{ITEM_CODE}، و مرتب‌سازیِ توپولوژیک برایِ ترتیبِ اجرا (نه صرفاً
display_order) — طبقِ سند."""

from __future__ import annotations

import decimal
import re
from dataclasses import dataclass

ALLOWED_VARIABLES = {"BASE_SALARY", "WORKED_DAYS", "CALENDAR_DAYS", "CHILDREN_COUNT", "WEEKLY_HOURS"}

_TOKEN_RE = re.compile(
    r"""
    (?P<NUMBER>\d+(\.\d+)?)
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<LBRACE>\{)
  | (?P<RBRACE>\})
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<COMMA>,)
  | (?P<GE>>=)
  | (?P<LE><=)
  | (?P<GT>>)
  | (?P<LT><)
  | (?P<EQ>=)
  | (?P<PLUS>\+)
  | (?P<MINUS>-)
  | (?P<STAR>\*)
  | (?P<SLASH>/)
  | (?P<WS>\s+)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            raise ValueError(f"نویسه‌ی غیرمجاز در فرمول: «{text[pos]}»")
        kind = match.lastgroup
        if kind != "WS":
            tokens.append(_Token(kind, match.group()))
        pos = match.end()
    return tokens


# --- گره‌هایِ AST -------------------------------------------------------
@dataclass(frozen=True)
class Num:
    value: decimal.Decimal


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class ItemRef:
    code: str


@dataclass(frozen=True)
class PolicyCall:
    code: str


@dataclass(frozen=True)
class BinOp:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Neg:
    operand: object


@dataclass(frozen=True)
class Compare:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class BoolAnd:
    left: object
    right: object


@dataclass(frozen=True)
class BoolOr:
    left: object
    right: object


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> _Token:
        token = self._peek()
        if token is None:
            raise ValueError("فرمول ناقص است.")
        self._pos += 1
        return token

    def _expect(self, kind: str) -> _Token:
        token = self._peek()
        if token is None or token.kind != kind:
            raise ValueError(f"در فرمول، «{kind}» انتظار می‌رفت.")
        return self._advance()

    def parse(self) -> object:
        node = self._parse_expr()
        if self._peek() is not None:
            raise ValueError(f"نویسه‌ی اضافه در فرمول: «{self._peek().text}»")
        return node

    def parse_condition(self) -> object:
        node = self._parse_or()
        if self._peek() is not None:
            raise ValueError(f"نویسه‌ی اضافه در شرط: «{self._peek().text}»")
        return node

    def _parse_or(self) -> object:
        node = self._parse_and()
        while self._peek() is not None and self._peek().kind == "IDENT" and self._peek().text == "OR":
            self._advance()
            node = BoolOr(node, self._parse_and())
        return node

    def _parse_and(self) -> object:
        node = self._parse_comparison()
        while self._peek() is not None and self._peek().kind == "IDENT" and self._peek().text == "AND":
            self._advance()
            node = BoolAnd(node, self._parse_comparison())
        return node

    def _parse_comparison(self) -> object:
        node = self._parse_expr()
        token = self._peek()
        if token is not None and token.kind in ("GT", "LT", "GE", "LE", "EQ"):
            self._advance()
            op = {"GT": ">", "LT": "<", "GE": ">=", "LE": "<=", "EQ": "="}[token.kind]
            return Compare(op, node, self._parse_expr())
        return node

    def _parse_expr(self) -> object:
        node = self._parse_term()
        while self._peek() is not None and self._peek().kind in ("PLUS", "MINUS"):
            op = self._advance().kind
            right = self._parse_term()
            node = BinOp("+" if op == "PLUS" else "-", node, right)
        return node

    def _parse_term(self) -> object:
        node = self._parse_factor()
        while self._peek() is not None and self._peek().kind in ("STAR", "SLASH"):
            op = self._advance().kind
            right = self._parse_factor()
            node = BinOp("*" if op == "STAR" else "/", node, right)
        return node

    def _parse_factor(self) -> object:
        token = self._peek()
        if token is None:
            raise ValueError("فرمول ناقص است.")
        if token.kind == "MINUS":
            self._advance()
            return Neg(self._parse_factor())
        if token.kind == "NUMBER":
            self._advance()
            return Num(decimal.Decimal(token.text))
        if token.kind == "LPAREN":
            self._advance()
            node = self._parse_expr()
            self._expect("RPAREN")
            return node
        if token.kind == "LBRACE":
            self._advance()
            ident = self._expect("IDENT")
            self._expect("RBRACE")
            return ItemRef(ident.text)
        if token.kind == "IDENT":
            self._advance()
            if token.text == "POLICY":
                self._expect("LPAREN")
                code = self._expect("IDENT")
                self._expect("RPAREN")
                return PolicyCall(code.text)
            if token.text not in ALLOWED_VARIABLES:
                raise ValueError(f"متغیرِ نامعتبر در فرمول: «{token.text}»")
            return Var(token.text)
        raise ValueError(f"نویسه‌ی غیرمنتظره در فرمول: «{token.text}»")


def parse_formula(text: str) -> object:
    """متنِ فرمول را پارس می‌کند؛ برایِ فرمولِ نامعتبر ValueError می‌دهد."""
    text = text.strip()
    if not text:
        raise ValueError("فرمول نمی‌تواند خالی باشد.")
    return _Parser(_tokenize(text)).parse()


def parse_condition(text: str) -> object:
    """شرطِ تخصیص (فصلِ ۷) را پارس می‌کند — همان گرامرِ فرمول به‌علاوهِ
    عملگرهایِ مقایسه (>، <، >=، <=، =) و AND/OR."""
    text = text.strip()
    if not text:
        raise ValueError("شرط نمی‌تواند خالی باشد.")
    return _Parser(_tokenize(text)).parse_condition()


def extract_item_refs(node: object) -> set[str]:
    """کدهایِ {ITEM_CODE}ی که این عبارت به آن‌ها ارجاع می‌دهد — برایِ
    ساختِ گرافِ وابستگی."""
    if isinstance(node, ItemRef):
        return {node.code}
    if isinstance(node, BinOp):
        return extract_item_refs(node.left) | extract_item_refs(node.right)
    if isinstance(node, Neg):
        return extract_item_refs(node.operand)
    if isinstance(node, (Compare, BoolAnd, BoolOr)):
        return extract_item_refs(node.left) | extract_item_refs(node.right)
    return set()


def evaluate(
    node: object,
    variables: dict[str, decimal.Decimal],
    resolved_items: dict[str, decimal.Decimal],
    policy_resolver,
) -> decimal.Decimal:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Var):
        if node.name not in variables:
            raise ValueError(f"متغیرِ «{node.name}» برایِ این کارمند در دسترس نیست.")
        return variables[node.name]
    if isinstance(node, ItemRef):
        if node.code not in resolved_items:
            raise ValueError(f"آیتمِ ارجاع‌داده‌شده «{node.code}» هنوز محاسبه نشده است.")
        return resolved_items[node.code]
    if isinstance(node, PolicyCall):
        value = policy_resolver(node.code)
        if value is None:
            raise ValueError(f"قانونِ «{node.code}» تعریف نشده است.")
        return value
    if isinstance(node, Neg):
        return -evaluate(node.operand, variables, resolved_items, policy_resolver)
    if isinstance(node, BinOp):
        left = evaluate(node.left, variables, resolved_items, policy_resolver)
        right = evaluate(node.right, variables, resolved_items, policy_resolver)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise ValueError("تقسیم بر صفر در فرمول.")
            return left / right
    if isinstance(node, Compare):
        left = evaluate(node.left, variables, resolved_items, policy_resolver)
        right = evaluate(node.right, variables, resolved_items, policy_resolver)
        if node.op == ">":
            return left > right
        if node.op == "<":
            return left < right
        if node.op == ">=":
            return left >= right
        if node.op == "<=":
            return left <= right
        return left == right
    if isinstance(node, BoolAnd):
        return bool(evaluate(node.left, variables, resolved_items, policy_resolver)) and bool(
            evaluate(node.right, variables, resolved_items, policy_resolver)
        )
    if isinstance(node, BoolOr):
        return bool(evaluate(node.left, variables, resolved_items, policy_resolver)) or bool(
            evaluate(node.right, variables, resolved_items, policy_resolver)
        )
    raise ValueError("گرهِ نامعتبر در فرمول.")


def topological_order(formulas: dict[str, object]) -> list[str]:
    """formulas: {item_code: ast}. ترتیبِ اجرا را بر اساسِ گرافِ
    وابستگیِ {ITEM_CODE} برمی‌گرداند؛ برایِ ارجاعِ دایره‌ای ValueError
    می‌دهد. آیتم‌هایی که در formulas نیستند (مثلاً فرمول ندارند) به‌عنوانِ
    برگ در نظر گرفته می‌شوند و در گراف شرکت نمی‌کنند."""
    deps = {code: extract_item_refs(ast) & formulas.keys() for code, ast in formulas.items()}
    visited: dict[str, int] = {}  # 0 = در حالِ بازدید، 1 = تمام‌شده
    order: list[str] = []

    def visit(code: str, stack: tuple[str, ...]) -> None:
        state = visited.get(code)
        if state == 1:
            return
        if state == 0:
            cycle = " -> ".join((*stack, code))
            raise ValueError(f"ارجاعِ دایره‌ای در فرمول‌ها: {cycle}")
        visited[code] = 0
        for dep in deps.get(code, ()):
            visit(dep, (*stack, code))
        visited[code] = 1
        order.append(code)

    for code in formulas:
        visit(code, ())
    return order
