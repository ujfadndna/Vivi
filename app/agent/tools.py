"""LangChain tools for the therapist agent."""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from urllib.parse import quote

from langchain_core.tools import tool

_TODO_DB: Path | None = None


def init_tools_db(db_path: Path) -> None:
    """Initialize persistence for tool-backed features."""
    global _TODO_DB

    _TODO_DB = Path(db_path)
    _TODO_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_TODO_DB)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                due_at TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    now = datetime.datetime.now()
    return now.strftime("%Y年%m月%d日 %H:%M:%S，%A")


@tool
def get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in (no API key needed)."""
    import urllib.request

    try:
        url = f"https://wttr.in/{quote(city)}?format=%C+%t+%h&lang=zh"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001 - tool should fail gracefully for the LLM.
        return f"获取{city}天气失败: {e}"


@tool
def calculate(expression: str) -> str:
    """Evaluate a safe math expression. Only arithmetic is allowed."""
    import ast
    import operator

    allowed_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    def _eval(node):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.operand))
        raise ValueError(f"不支持的表达式: {ast.dump(node)}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        rounded = round(result, 10)
        if isinstance(rounded, float):
            return str(rounded).rstrip("0").rstrip(".")
        return str(rounded)
    except Exception as e:  # noqa: BLE001 - return tool errors as model-readable text.
        return f"计算失败: {e}"


@tool
def add_todo(user_id: str, content: str, due_at: str | None = None) -> str:
    """Add a todo item for the user."""
    if _TODO_DB is None:
        return "待办功能未初始化"
    with sqlite3.connect(str(_TODO_DB)) as conn:
        conn.execute(
            "INSERT INTO todos (user_id, content, due_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, content, due_at, datetime.datetime.now().isoformat()),
        )
    return f"已记录: {content}"


@tool
def list_todos(user_id: str) -> str:
    """List pending todo items for the user."""
    if _TODO_DB is None:
        return "待办功能未初始化"
    with sqlite3.connect(str(_TODO_DB)) as conn:
        rows = conn.execute(
            "SELECT content, due_at FROM todos WHERE user_id=? AND done=0 ORDER BY id DESC LIMIT 10",
            (user_id,),
        ).fetchall()
    if not rows:
        return "没有待办事项"
    items = [f"- {row[0]}" + (f"（{row[1]}）" if row[1] else "") for row in rows]
    return "\n".join(items)


ALL_TOOLS = [get_current_time, get_weather, calculate, add_todo, list_todos]
