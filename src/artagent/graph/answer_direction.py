"""Check the supported White Balance temperature directions against cited evidence."""

from collections.abc import Iterator
from dataclasses import dataclass
import re
from typing import Literal


# English UI labels can be directly followed by a Korean particle.
_TEMPERATURE = r"(?<![a-z])(?:temperature|kelvin)(?![a-z])|색\s*온\s*도|온도\s*슬라이더|켈빈"
_TEMPERATURE_CONTROL = re.compile(_TEMPERATURE, re.I)
_WHITE_BALANCE = re.compile(
    rf"{_TEMPERATURE}|(?<![a-z])(?:white[-\s]*balance|wb)(?![a-z])|화이트\s*밸런스|백\s*균형",
    re.I,
)
_CAST = re.compile(
    r"(?P<right>노랗|노래요|노란|누렇|누런|\byellow(?:ish)?\b)"
    r"|(?P<left>푸르|푸른|파랗|파래요|파란|\bblu(?:e|ish)\b)",
    re.I,
)
_ADJUSTMENT_QUESTION = re.compile(
    r"조[정절]|보정|손대|만지|(?:어디|무엇)부터|없애|줄[이여]|빼|중화|어느\s*(?:쪽|방향)"
    r"|\b(?:adjust|correct|fix|reduce|remove|neutraliz\w*)\b",
    re.I,
)
_EFFECT = re.compile(
    r"(?P<left>차갑(?:게|고|다|습니다)|차가워|차가운|서늘하(?:게|다)|\bcool(?:er)?\b)"
    r"|(?P<right>따뜻하(?:게|고|다)|따뜻해|따뜻한|따듯하(?:게|고|다)|따듯해|따듯한|\bwarm(?:er)?\b)",
    re.I,
)
_COLOR_EFFECT = re.compile(
    r"(?P<left>푸르러[지집]|파래[지집]|(?:푸른|파란)\s*색으로|(?:푸르게|파랗게)\s*(?:만들|변))"
    r"|(?P<right>노래[지집]|누레[지집]|노란\s*색으로|(?:노랗게|누렇게)\s*(?:만들|변))",
)
_WEAKER_EFFECT = re.compile(
    r"^\s*(?:색(?:감|조)?|기운|느낌)?(?:을|를|이|가)?\s*(?:더\s*)?(?:줄[이어여]|완화|중화|없애|빼|가라앉)",
)
_OPPOSITE = {"right": "left", "left": "right"}
_EXPLICIT_GOAL = re.compile(r"(?:만들|연출하|표현하|(?:게|히)\s*하)(?:고\s*싶|려면|기\s*위해)")
_DIRECTION = re.compile(
    r"(?P<left>왼쪽|좌측|(?<![a-z])left(?![a-z]))"
    r"|(?P<right>오른쪽|우측|(?<![a-z])right(?![a-z]))",
    re.I,
)
_AMOUNT = r"(?:(?:조금씩|조금|약간|살짝|한\s*단계|소폭|미세하게|더|좀)\s*){0,3}"
_VALUE_CHANGE = r"(?P<left>낮[추춰출]|내리|내려|내릴|감소)|(?P<right>높[이여일]|올리|올려|올릴|증가)"
_VALUE_DIRECTION = re.compile(
    rf"(?:{_TEMPERATURE}|온도)(?:\s*슬라이더)?(?:\s*(?:값|수치))?(?:을|를|은|는)?\s*"
    rf"{_AMOUNT}(?:{_VALUE_CHANGE})",
    re.I,
)
_FOLLOWUP_DIRECTION = re.compile(
    rf"^(?:그\s*다음(?:에)?\s*|이어서\s*|다시\s*)+{_AMOUNT}(?:{_VALUE_CHANGE})",
)
_OTHER_CONTROL = re.compile(
    r"(?<![a-z])(?:tint|exposure)(?![a-z])|틴트|색조\s*슬라이더|노출\s*보정|채도|대비",
    re.I,
)
_CONTROL_LABEL = re.compile(rf"(?P<temperature>{_TEMPERATURE})|(?P<other>{_OTHER_CONTROL.pattern})", re.I)
_JOINT_CONTROLS = re.compile(r"\s*(?:\(|\)?\s*(?:와|과|및|/|·|\+)\s*\(?)\s*")
_CONDITION = re.compile(r"으면|라면|다면|려면|이면|하면|보이면|돌면|아니면|경우|(?:있을|없을|않을|아닐|인|일)\s*때")
_NEGATED_CAST = re.compile(
    r"(?:없|않)(?:으|다)?면|아니(?:면|라면)|(?:없을|않을|아닐)\s*때|(?:없[는을]|않[는을]|아닌)\s*경우",
)
_CREATIVE_PURPOSE = re.compile(r"창작\s*목적|의도적|강화하|연출하|표현하")
_PRESENT_CAST = re.compile(r"^\s*(?:색(?:감)?|빛|기(?:운)?)(?:이|가|은|는)?\s*(?:있|돌|나|보이)")
_SETTING_TARGET = re.compile(
    r"\d+(?:[.,]\d+)*\s*(?:k(?![a-z])|켈빈|(?:으로|로)\s*(?:설정|맞추|바꾸))",
    re.I,
)
_NEGATIVE_PREFIX = re.compile(r"\b(?:not(?:\s+to)?(?:\s+the)?|avoid(?:\s+the)?)\s*$", re.I)
_NEGATIVE_SUFFIX = re.compile(
    r"^\s*(?:으로|로|이|가|을|를|은|는|에)?\s*"
    r"(?:아니라|아닙니다|아닌|말고|피하|금지|(?:옮기|이동하|움직이|조정하|조절하|돌리|밀)?지\s*(?:마|않)"
    r"|(?:옮겨|이동해|움직여|돌려|밀어)서는\s*안)",
)
_EFFECT_DESCRIPTION = re.compile(
    r"^(?:은|는|면|수록)\s|.{0,24}(?:(?:옮기|이동하|움직이|밀|가)면|(?:옮길|이동할|움직일|밀|갈)수록)"
    r"|^\s+(?:makes?|cools?|warms?)\b",
    re.I,
)
_RECOMMENDATION = re.compile(r"세요|십시오|해야|권장|추천|는\s*편이|면\s*됩니다")
_CONTROL_CHANGE = re.compile(r"조[정절]|보정|맞추|맞춰|변경|바꾸|설정|옮기|이동|움직|돌리|밀")
_COLOR_ADVICE = re.compile(r"만들|만드|연출|표현|하(?:세|십)|해\s*보")
_CITATION = re.compile(r"\[C\d+S\d+\]")
_ART_NAME = re.compile(r"(?<![a-z])art(?![a-z])", re.I)
_PRODUCT_SCOPE = re.compile(
    r"(?<![a-z])(?:(?P<art>art)(?:\s*(?:와|과)\s*(?:rawtherapee|rawpedia))?"
    r"|(?P<reference>rawtherapee|rawpedia|로테라피))(?![a-z])\s*"
    r"(?:에서는|에서|의|기준|문서\s*(?:에서|에\s*따르면|기준|상)|에\s*따르면)",
    re.I,
)
_TEMPERATURE_EVIDENCE = (
    "moving it to the left makes the image cooler (bluish); "
    "moving it to the right makes it warmer (yellowish)."
)


@dataclass(frozen=True, slots=True)
class TemperatureGoal:
    """The requested direction and the neutral correction for the observed cast."""

    direction: str
    correction_for_cast: str | None


@dataclass(frozen=True, slots=True)
class _Condition:
    start: int
    cast_correction: str | None = None
    requested_direction: str | None = None

    def resolve(self, goal: TemperatureGoal) -> tuple[str, bool]:
        if self.cast_correction is not None and self.cast_correction != goal.correction_for_cast:
            return self.requested_direction or self.cast_correction, False
        if self.requested_direction is not None and self.requested_direction != goal.direction:
            return self.requested_direction, False
        return goal.direction, True


@dataclass(frozen=True, slots=True)
class _Adjustment:
    direction: str | None
    effects: frozenset[str]
    condition: _Condition | None
    scope: str | None
    role: Literal["recommendation", "description", "avoid", "unverified_value"]


def _only_direction(pattern: re.Pattern[str], text: str) -> str | None:
    matches = {match.lastgroup for match in pattern.finditer(text)}
    return matches.pop() if len(matches) == 1 else None


def _cast_correction(text: str) -> str | None:
    return _OPPOSITE.get(_only_direction(_CAST, text))


def _reported_effects(text: str) -> frozenset[str]:
    effects = set()
    for pattern in (_EFFECT, _COLOR_EFFECT):
        for match in pattern.finditer(text):
            direction = match.lastgroup
            weaker = _WEAKER_EFFECT.match(text[match.end():]) or text[:match.start()].rstrip().endswith("덜")
            effects.add(_OPPOSITE[direction] if weaker else direction)
    return frozenset(effects)


def temperature_goal(question: str, confirmed_goal: str | None = None) -> TemperatureGoal | None:
    """Resolve unambiguous correction or creative intent from the actual question."""
    if not _WHITE_BALANCE.search(question):
        return None
    if _OTHER_CONTROL.search(question) and not _TEMPERATURE_CONTROL.search(question):
        return None
    explicit = _EXPLICIT_GOAL.search(question)
    if explicit:
        clauses = re.split(r"[.!?,]|하지만|지만|말고|나와서|보여서", question[:explicit.start()])
        target = clauses[-1].strip()
        if re.search(r"않|말고|\bnot\b", target, re.I):
            return None
        effect = _only_direction(_EFFECT, target) or _only_direction(_CAST, target)
        if effect:
            return TemperatureGoal(effect, _cast_correction(" ".join(clauses[:-1])))
    if _ADJUSTMENT_QUESTION.search(question) or _VALUE_DIRECTION.search(question):
        correction = _cast_correction(question)
        excess = re.search(r"(?:너무|지나치게|과하게|too)\s+([^,.!?]+)", question, re.I)
        if excess and not correction:
            correction = _OPPOSITE.get(_only_direction(_EFFECT, excess[1]))
        if correction:
            return TemperatureGoal(correction, correction)
    if confirmed_goal:
        correction = _cast_correction(confirmed_goal) if _ADJUSTMENT_QUESTION.search(confirmed_goal) else None
        direction = correction or _only_direction(_EFFECT, confirmed_goal)
        if direction:
            return TemperatureGoal(direction, _cast_correction(question))
    return None


def _cast_condition(text: str) -> _Condition | None:
    """Distinguish a change to the observed cast from a separate creative goal."""
    casts = list(_CAST.finditer(text))
    for index, cast in enumerate(casts):
        next_cast = casts[index + 1].start() if index + 1 < len(casts) else len(text)
        condition = _CONDITION.search(text, cast.end(), min(cast.end() + 28, next_cast))
        if condition:
            detail = text[cast.end():condition.end()]
            if _NEGATED_CAST.search(detail):
                return _Condition(cast.start())
            correction = _OPPOSITE[cast.lastgroup]
            if _CREATIVE_PURPOSE.search(text[:condition.end()]):
                observed = correction if _PRESENT_CAST.match(detail) else None
                desired = _only_direction(_EFFECT, detail) or cast.lastgroup
                return _Condition(cast.start(), observed, desired)
            return _Condition(cast.start(), correction)
    return None


def _product_scope(text: str) -> str | None:
    scopes = {match.lastgroup for match in _PRODUCT_SCOPE.finditer(text)}
    if "art" in scopes:
        return "art"
    return "reference" if scopes else None


def _named_control(text: str) -> str | None:
    """Resolve which control the following action refers to."""
    labels = list(_CONTROL_LABEL.finditer(text))
    if not labels:
        return None
    last = labels[-1]
    if last.lastgroup == "temperature":
        return "temperature"
    for previous in reversed(labels[:-1]):
        if not _JOINT_CONTROLS.fullmatch(text[previous.end():last.start()]):
            break
        if previous.lastgroup == "temperature":
            return "temperature"
        last = previous
    return "other"


def _sentence_adjustments(sentence: str) -> Iterator[_Adjustment]:
    condition = None
    scope = None
    control = "temperature"
    for clause in re.split(r"(?<!\d),|,(?!\d)", sentence):
        clause = clause.strip()
        uses_temperature = _TEMPERATURE_CONTROL.search(clause)
        directions = sorted(
            [*_DIRECTION.finditer(clause), *_VALUE_DIRECTION.finditer(clause), *_FOLLOWUP_DIRECTION.finditer(clause)],
            key=lambda match: match.start(),
        )
        if not directions:
            control = _named_control(clause) or control
            if control == "other":
                condition = scope = None
                continue
            scope = _product_scope(clause) or scope
            condition = _cast_condition(clause) or condition
            effects = _reported_effects(clause)
            control_change = _CONTROL_CHANGE.search(clause)
            if _RECOMMENDATION.search(clause) and (
                (uses_temperature and control_change)
                or (effects and (_WHITE_BALANCE.search(clause) or control_change or _COLOR_ADVICE.search(clause)))
            ):
                role = "unverified_value" if uses_temperature and _SETTING_TARGET.search(clause) else "recommendation"
                yield _Adjustment(None, effects, condition, scope, role)
            continue

        previous_end = 0
        for index, match in enumerate(directions):
            before = clause[previous_end:match.start()]
            previous_end = match.end()
            control = _named_control(before + match.group()) or control
            if control == "other":
                condition = scope = None
                continue
            condition = _cast_condition(before) or condition
            scope = _product_scope(before) or scope
            next_start = directions[index + 1].start() if index + 1 < len(directions) else len(clause)
            following = clause[match.end():next_start]
            if index + 1 < len(directions):
                next_condition = _cast_condition(following)
                if next_condition:
                    following = following[:next_condition.start]
            if other := _OTHER_CONTROL.search(following):
                following = following[:other.start()]
            trailing_scope = _product_scope(following)
            claim_scope = "art" if "art" in (scope, trailing_scope) else trailing_scope or scope
            effects = _reported_effects(following)
            if _NEGATIVE_SUFFIX.match(following) or _NEGATIVE_PREFIX.search(before):
                role = "avoid"
            elif effects and _EFFECT_DESCRIPTION.match(following) and not _RECOMMENDATION.search(following):
                role = "description"
            else:
                role = "recommendation"
            yield _Adjustment(match.lastgroup, effects, condition, claim_scope, role)


def temperature_direction_issue(
    question: str,
    answer: str,
    goal: TemperatureGoal,
    citations: list[dict],
    *,
    supported: bool,
) -> str | None:
    """Return a reason to withhold a conflicting or unverified prescription."""
    adjustments = [
        action
        for sentence in re.split(r"(?<!\d)\.|\.(?!\d)|[!?;\n]", _CITATION.sub("", answer))
        for action in _sentence_adjustments(sentence)
    ]
    applicable_action = False
    asks_about_art = bool(_ART_NAME.search(question))
    for action in adjustments:
        expected, applies = action.condition.resolve(goal) if action.condition else (goal.direction, True)
        if action.scope == "art" or action.role == "unverified_value":
            return "unverified_action"
        if action.role == "avoid":
            if action.direction == expected:
                return "conflict"
            continue
        if action.effects - {action.direction or expected}:
            return "conflict"
        if action.role == "description":
            continue
        if asks_about_art and action.scope != "reference":
            return "unverified_action"
        # A generic adjustment or inspection does not assert a slider direction.
        if action.direction is None:
            continue
        if action.direction != expected:
            return "conflict"
        if applies:
            applicable_action = True

    if applicable_action or (supported and (adjustments or _TEMPERATURE_CONTROL.search(answer))):
        has_direction_evidence = any(
            evidence["source_type"] == "rawpedia"
            and evidence["doc_id"] == "rawpedia:White_Balance"
            and _TEMPERATURE_EVIDENCE in " ".join(evidence["text"].lower().split())
            for evidence in citations
        )
        if not applicable_action or not has_direction_evidence:
            return "unverified_action"
    return None
