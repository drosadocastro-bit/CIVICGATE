"""A bounded, fail-closed request-scope signal, independent of hard tripwires.

This is a deliberately small research-intake grammar, not a natural-language
classifier or a second authority issuer. Only the existing policy can permit.
Absence of a consequential keyword is never sufficient evidence for permission.
Unrecognized, mixed, quoted or negated instructions require clarification.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import TypeAdapter

from civicgate.governance.authority import denied_reasons
from civicgate.models.requests import TOOLS, Search, Text

RISK_VERSION = "channel-a-request-risk-r1-intent-binding-1"

# These describe read/research operations, not examples from the challenge set.
_READ_HEAD = re.compile(
    r"^(?:get|show|find|list|read|retrieve|lookup|look up|search|summarize|resolve|"
    r"fetch|consult|recupera|consulta|busca|muestra|lee|enumera|resume|localiza|"
    r"obten|obtener|buscar|consultar|recuperar|mostrar)\b"
)
_DISCUSSION_HEAD = re.compile(
    r"^(?:explain|describe|compare|analyze|analyse|discuss|study|research|"
    r"explica|describe|compara|analiza|discute|estudia|investiga)\b"
)
_SCOPE = re.compile(
    r"\b(?:public|federal|awards?|spending|records?|data|recipients?|"
    r"publicos?|publicas?|adjudicaciones?|contratos?|gasto|datos|registros?)\b"
)
_ACTION = re.compile(
    r"\b(?:approve|authorize|certify|choose|decide|determine|disburse|enact|execute|"
    r"grant|issue|modify|order|pay|release|replace|restrict|select|transfer|update|"
    r"write|aprobar|aprueba|autoriza|autorizar|certifica|certificar|elige|elegir|"
    r"escoge|decide|decidir|declara|declarar|determina|determinar|desembolsa|"
    r"emite|emitir|modifica|modificar|ordena|ordenar|paga|pagar|reemplaza|"
    r"restringe|selecciona|transfiere|actualiza|concede|adjudica)\b|"
    r"\b(?:award|contract)\s+(?:an?|the|this|that|these|those|it|them)\b"
)
_SHORTHAND = re.compile(
    r"^(?:public|federal)(?: (?:public|federal))? "
    r"(?:awards?|spending|research|records?|data|recipients?)"
    r"(?: (?:awards?|spending|research|records?|data|recipients?|details|summary|search))*$|"
    r"^(?:datos|registros|adjudicaciones|gasto) public(?:o|a|os|as)$"
)
# Capitalization cannot distinguish an entity from an unknown instruction.
# Only an explicitly labeled JSON string is a name literal. Outside that
# literal the complete clause must still satisfy the factual-read grammar.
_NAMED_FIELD = re.compile(
    r"\b(?P<field>(?P<recipient_label>(?i:recipient|destinatario))|(?i:agency|agencia))[ \t]+"
    r"(?:(?i:named|called|llamado|llamada)[ \t]+)?"
    r'(?P<name>"(?:[^"\\\x00-\x1f]|\\.)*")'
)
_NAME_VALUE = TypeAdapter(Text)
_UNPARSED_QUOTES = frozenset("\"'“”‘’«»")
_CLAUSE = re.compile(r"[.;!?\n]+|,\s*|\b(?:and then|then|and|but|y|luego|despues|pero|ahora)\b")
_POLITE = re.compile(
    r"^(?:please|could you|can you|por favor|puedes|podrias|solo|only|first|primero)\s+"
)
_NEGATION = re.compile(r"^(?:do not|don't|never|no|sin)\b")
_SHORTHAND_WORDS = frozenset(
    "public federal award awards spending records record data research details search "
    "recipient recipients contract contracts lookup summary for of the a an and in "
    "publico publica publicos publicas adjudicacion adjudicaciones contratos contrato "
    "datos registros registro gasto investigacion detalles consulta de del la las el los".split()
)
_READ_WORDS = _SHORTHAND_WORDS | frozenset(
    "factual bounded matching known detail information amount amounts date dates candidates "
    "agency agencies destinatario agencia "
    "recorded published history historical fields identifiers identifier page total "
    "totals one this that these those me please only from by with on about to during "
    "academic report reports university prevention research federal-award puerto rico "
    "los las un una unos unas para por en con sobre informacion importes importe "
    "fechas fecha publicados publicadas publicado publicada historicos historicas "
    "historial campos identificadores universitario universitaria informe informes "
    "academico academica este esta estos estas uno una solo".split()
)


@dataclass(frozen=True)
class RequestRisk:
    intent: Literal["READ_CANDIDATE", "DISCUSSION_OR_NEGATION", "UNRESOLVED"]
    reasons: tuple[str, ...] = ()
    version: str = RISK_VERSION


def _normalize(text: str) -> str:
    # Preserve the raw input for audit; normalize only this independent signal.
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    text = "".join(
        char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char)
    )
    return re.sub(r"[^\S\n]+", " ", text).strip()


def _name_literal(match: re.Match[str]) -> str | None:
    try:
        raw_value = json.loads(match["name"])
        value = _NAME_VALUE.validate_python(raw_value)
    except ValueError:
        return None
    if any(unicodedata.category(char).startswith("C") for char in raw_value):
        return None
    if denied_reasons(raw_value):
        return None
    return value


def literal_proposal_reasons(
    request: str, tool: str, arguments_json: str | None
) -> tuple[str, ...]:
    """Compare explicit names with effective Search filters, never rewrite them.

    Only the two existing Search tools express this scoped retrieval contract.
    Exact decoded Text equality is required; no case/accent/Unicode folding or
    entity resolution is inferred. Unsupported syntax remains held by the
    separate complete-clause request-risk check.
    """
    constraints = [
        (
            "recipient_name" if match["recipient_label"] is not None else "awarding_agency",
            value,
        )
        for match in _NAMED_FIELD.finditer(request)
        if (value := _name_literal(match)) is not None
    ]
    if not constraints:
        return ()
    if tool not in {"find_federal_awards", "summarize_federal_spending"}:
        return ("NAME_LITERAL_PROPOSAL_UNSUPPORTED",)
    if arguments_json is None:
        return ("NAME_LITERAL_PROPOSAL_UNAVAILABLE",)
    try:
        effective = TOOLS[tool].model_validate_json(arguments_json)
    except (ValueError, TypeError):
        return ("NAME_LITERAL_PROPOSAL_UNAVAILABLE",)
    if not isinstance(effective, Search):
        return ("NAME_LITERAL_PROPOSAL_UNSUPPORTED",)
    if any(getattr(effective, field) != value for field, value in constraints):
        return ("NAME_LITERAL_PROPOSAL_MISMATCH",)
    return ()


def assess_request_risk(request: str) -> RequestRisk:
    """Recognize a narrow read candidate; uncertainty always requests review.

    Discussion and negation are distinct from an action instruction, but neither
    proves that a supplied tool proposal answers the question. They therefore
    request review rather than being an escape hatch for mixed instructions.
    """

    def named_literal(match: re.Match[str]) -> str:
        # The same decoder supplies scope constraints and syntax recognition.
        # Invalid or tripwire-bearing literals remain visible and reviewable.
        return match["field"] if _name_literal(match) is not None else match[0]

    text = _normalize(_NAMED_FIELD.sub(named_literal, request))
    # Tokenization must not silently discard unsupported or broken delimiters.
    unparsed_quotes = any(char in _UNPARSED_QUOTES for char in text)
    # Preserve the established terse research intake (e.g. "public awards").
    if _SHORTHAND.fullmatch(text.rstrip(".")):
        return RequestRisk("READ_CANDIDATE")
    clauses = [clause.strip(" :\t\r") for clause in _CLAUSE.split(text) if clause.strip()]
    if not clauses:
        return RequestRisk("UNRESOLVED", ("REQUEST_INTENT_UNRESOLVED",))
    discussion = False
    read = False
    for clause in clauses:
        while True:
            stripped = _POLITE.sub("", clause)
            if stripped == clause:
                break
            clause = stripped
        if _NEGATION.match(clause) or _DISCUSSION_HEAD.match(clause):
            discussion = True
            continue
        if _ACTION.search(clause):
            return RequestRisk("UNRESOLVED", ("CONSEQUENTIAL_REQUEST_REQUIRES_REVIEW",))
        if unparsed_quotes:
            return RequestRisk("UNRESOLVED", ("NAME_LITERAL_UNRESOLVED",))
        head = _READ_HEAD.match(clause)
        if head is None or not _SCOPE.search(clause):
            return RequestRisk("UNRESOLVED", ("REQUEST_INTENT_UNRESOLVED",))
        # Recognition covers the complete clause, not merely a benign prefix.
        # Free-form names, unknown verbs, purpose clauses and unsupported syntax
        # remain reviewable; a model cannot grant missing grammar coverage.
        tail = re.findall(r"\b\w+\b", clause[head.end() :])
        if any(
            word not in _READ_WORDS
            and not word.isdecimal()
            and re.fullmatch(r"fy\d{4}", word) is None
            for word in tail
        ):
            return RequestRisk("UNRESOLVED", ("REQUEST_INTENT_UNRESOLVED",))
        read = True
    if discussion:
        return RequestRisk("DISCUSSION_OR_NEGATION", ("REQUEST_SCOPE_REQUIRES_REVIEW",))
    if read:
        return RequestRisk("READ_CANDIDATE")
    return RequestRisk("UNRESOLVED", ("REQUEST_INTENT_UNRESOLVED",))
