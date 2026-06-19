"""MVP safety guardrails implemented with local regex rules.

This module performs lightweight crisis-risk detection before LLM handling.
The current MVP uses deterministic keyword patterns and can be replaced later
with a dedicated classifier such as MindGuard 4B.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["safe", "unsafe_self_harm_risk", "unsafe_harm_to_others"]


_SELF_HARM_PATTERNS: list[str] = [
    r"不想活(?:了)?",
    r"想死",
    r"去死",
    r"自杀",
    r"自残",
    r"结束(?:自己的)?生命",
    r"活不下去(?:了)?",
    r"死了算了",
    r"割腕",
    r"跳楼",
    r"上吊",
    r"轻生",
    r"寻死",
    r"了结自己",
    r"伤害自己",
]

_HARM_OTHERS_PATTERNS: list[str] = [
    r"杀(?:了|掉|死)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"弄死(?:他|她|它|他们|她们|某人|别人|对方)",
    r"打死(?:他|她|它|他们|她们|某人|别人|对方)",
    r"砍(?:了|死|伤)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"捅(?:了|死|伤)?(?:他|她|它|他们|她们|某人|别人|对方)",
    r"报复(?:他|她|它|他们|她们|某人|别人|对方)",
    r"伤害(?:他|她|它|他们|她们|某人|别人|对方)",
    r"干掉(?:他|她|它|他们|她们|某人|别人|对方)",
    r"让(?:他|她|它|他们|她们|某人|别人|对方)付出代价",
]


@dataclass
class SafetyResult:
    risk_level: RiskLevel
    matched_pattern: str | None
    confidence: float


def check_safety(text: str) -> SafetyResult:
    """Check user input for crisis risk with self-harm taking priority."""
    text_norm = text.strip()

    for pattern in _SELF_HARM_PATTERNS:
        if re.search(pattern, text_norm):
            return SafetyResult(
                risk_level="unsafe_self_harm_risk",
                matched_pattern=pattern,
                confidence=1.0,
            )

    for pattern in _HARM_OTHERS_PATTERNS:
        if re.search(pattern, text_norm):
            return SafetyResult(
                risk_level="unsafe_harm_to_others",
                matched_pattern=pattern,
                confidence=1.0,
            )

    return SafetyResult(
        risk_level="safe",
        matched_pattern=None,
        confidence=1.0,
    )


CRISIS_RESPONSE_SELF_HARM = """
我注意到你提到了可能伤害自己的想法，这让我很担心你的安全。
如果你现在有立即危险，请马上拨打 120 或 110，或请身边的人陪你去最近的急诊。
你也可以联系全国心理援助热线：400-161-9995。

请先把可能伤害自己的物品放到离你更远的地方，尽量不要独处，并联系一个你信任的人来陪你。
我不能替代专业救援或医疗帮助，但我可以陪你一起把接下来最安全的一步说清楚。
""".strip()

CRISIS_RESPONSE_HARM_OTHERS = """
我注意到你提到了可能伤害他人的想法，这需要立刻把安全放在第一位。
请先离开对方或任何可能使用的危险物品，去一个有人在、相对安全的地方。
如果你担心自己会马上行动，请立即拨打 110，或联系身边可信任的人帮你一起控制局面。
你也可以联系全国心理援助热线：400-161-9995，尽快获得专业支持。
""".strip()


def get_crisis_response(risk_level: RiskLevel) -> str:
    """Return the fixed crisis response for a risk level."""
    if risk_level == "unsafe_self_harm_risk":
        return CRISIS_RESPONSE_SELF_HARM
    if risk_level == "unsafe_harm_to_others":
        return CRISIS_RESPONSE_HARM_OTHERS
    return ""
