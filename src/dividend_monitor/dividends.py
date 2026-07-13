"""Conservative classifier for explicit dividend events in public text."""

# Unicode escape-heavy matching patterns remain readable in their source form.
# ruff: noqa: E501

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import HttpUrl

from .models import DividendEvent, DividendEventType, DividendStatus, ShareType
from .sources.parsing import parse_date

_DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"


def _rx(pattern: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), pattern)


_DIVIDEND_WORD = _rx(r"(?:\u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434|dividend)")


def _status(text: str) -> tuple[DividendStatus | None, DividendEventType | None]:
    if (
        "\u0438\u0437\u043c\u0435\u043d\u0435\u043d" in text
        and "\u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u0430\u044f \u043f\u043e\u043b\u0438\u0442\u0438\u043a"
        in text
    ):
        return "approved", "policy_change"
    if "\u043e\0442\u043c\u0435\u043d" in text or "\u043e\0442\u043a\u0430\u0437" in text:
        return "cancelled", "cancellation"
    if re.search(
        _rx(
            r"(?:\u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430|\u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435).{0,80}\u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u043e\u0439\s+\u043f\u043e\u043b\u0438\u0442\u0438\u043a"
        ),
        text,
    ):
        return "approved", "policy_change"
    if re.search(
        _rx(
            r"\b(?:\u043e\u0442\u043a\u0430\u0437|\u043e\0442\u043c\u0435\u043d|\u043d\u0435\s+\u0432\u044b\u043f\u043b\u0430\u0442|cancel|reject)"
        ),
        text,
    ):
        return "cancelled", "cancellation"
    if re.search(
        _rx(
            r"(?:\u0432\u044b\u043f\u043b\u0430\u0447\u0435\u043d|\u0432\u044b\u043f\u043b\u0430\u0442\u0430\s+\u0437\u0430\u0432\u0435\u0440\u0448|paid)"
        ),
        text,
    ):
        return "paid", "payment"
    if re.search(
        _rx(
            r"(?:\u0443\u0442\u0432\u0435\u0440\u0436\u0434|\u0440\u0435\u0448\u0435\u043d\u0438\u0435\s+\u043e\u0431\u0449\u0435\u0433\u043e\s+\u0441\u043e\u0431\u0440\u0430\u043d|approved)"
        ),
        text,
    ):
        return "approved", "approval"
    if re.search(
        _rx(
            r"(?:\u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u043b|\u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f|recommend)"
        ),
        text,
    ):
        return "recommended", "recommendation"
    return None, None


def _date_after(text: str, pattern: str) -> datetime | None:
    match = re.search(rf"(?:{_rx(pattern)}).{{0,100}}?({_DATE})", text)
    if not match:
        return None
    date_match = re.search(_DATE, match.group(0))
    if not date_match:
        return None
    value = date_match.group(0).replace("/", ".").replace("-", ".")
    try:
        return datetime.strptime(value, "%d.%m.%Y").replace(tzinfo=UTC)
    except ValueError:
        return parse_date(value)


def _period(text: str) -> str | None:
    patterns = (
        r"(?:\u0437\u0430\s+)?(\d{1,2}\s+\u043c\u0435\u0441\u044f\u0446\u0435\u0432\s+20\d{2}\s+\u0433\u043e\u0434)",
        r"(?:\u0437\u0430\s+)?(20\d{2}\s+\u0433\u043e\u0434)",
        r"(?:for\s+)?((?:Q[1-4]|H1|9M|FY)\s+20\d{2})",
    )
    for pattern in patterns:
        match = re.search(_rx(pattern), text)
        if match:
            return match.group(1)
    return None


def _amount(text: str) -> Decimal | None:
    ruble_words = (
        "\u0440\u0443\u0431",
        "\u0440\u0443\u0431\u043b\u044f",
        "\u0440\u0443\u0431\u043b\u0435\u0439",
    )
    for number_match in reversed(list(re.finditer(r"\d[\d\s]*(?:[,.]\d+)?", text))):
        tail = text[number_match.end() : number_match.end() + 80]
        if (
            any(currency in tail for currency in (*ruble_words, "RUB", "\u20bd"))
            and "\u043d\u0430" in tail
            and "\u0430\u043a\u0446\u0438\u044e" in tail
        ):
            try:
                return Decimal(number_match.group(0).replace(" ", "").replace(",", "."))
            except InvalidOperation:
                return None
    ruble = "\u0440\u0443\u0431"
    amount_pattern = (
        r"(\d[\d\s]*(?:[,.]\d+)?)\s*(?:"
        + re.escape("\u20bd")
        + "|"
        + re.escape(ruble)
        + r"(?:\u043b\u0435\u0439|\u043b\u044f)?|RUB)\s+"
        + re.escape("\u043d\u0430")
        + r"\s+(?:"
        + re.escape("\u043e\0434\u043d\u0443")
        + r"\s+)?"
        + re.escape("\u0430\u043a\u0446\u0438\u044e")
    )
    match = re.search(
        _rx(
            r"(\d[\d\s]*(?:[,.]\d+)?)\s*(?:\u20bd|\u0440\u0443\u0431(?:\u043b\u0435\u0439|\u043b\u044f)?|RUB)\s+\u043d\u0430\s+(?:\u043e\u0434\u043d\u0443\s+)?\u0430\u043a\u0446\u0438\u044e"
        ),
        text,
    )
    match = match or re.search(amount_pattern, text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def _share_type(text: str) -> ShareType:
    if re.search(
        _rx(
            r"(?:\u043f\u0440\u0438\u0432\u0438\u043b\u0435\u0433\u0438\u0440\u043e\u0432\u0430\u043d|preferred|preference)"
        ),
        text,
    ):
        return "preferred"
    if re.search(
        _rx(r"(?:\u043e\u0431\u044b\u043a\u043d\u043e\u0432\u0435\u043d\u043d|ordinary|common)"),
        text,
    ):
        return "ordinary"
    return "unspecified"


def _phrase(text: str, keyword: str) -> str | None:
    match = re.search(rf"[^.!?]*{keyword}[^.!?]*", text)
    return match.group(0).strip() if match else None


def classify_dividend_event(
    text: str, source_url: HttpUrl, ticker: str | None = None
) -> DividendEvent | None:
    normalized = re.sub(r"\s+", " ", text.casefold().replace("\u0451", "\u0435")).strip()
    if not re.search(_DIVIDEND_WORD, normalized):
        return None
    status, event_type = _status(normalized)
    if not status or not event_type:
        return None
    policy_change = _phrase(
        normalized,
        "\u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u043e\u0439 \u043f\u043e\u043b\u0438\u0442\u0438\u043a",
    )
    board = _phrase(
        normalized,
        "\u0441\u043e\u0432\u0435\u0442 \u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440\u043e\u0432",
    )
    shareholder = _phrase(
        normalized, "\u043e\u0431\u0449\u0435\u0435 \u0441\u043e\u0431\u0440\u0430\u043d"
    )
    rasbu_profit = (
        _phrase(
            normalized,
            "\u0447\u0438\u0441\u0442\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c",
        )
        if ticker == "LSNGP"
        else None
    )
    dividend_base = (
        _phrase(
            normalized,
            "\u0434\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u0430\u044f \u0431\u0430\u0437\u0430",
        )
        if ticker == "LSNGP"
        else None
    )
    preferred_payment = (
        _phrase(
            normalized,
            "\u043f\u0440\u0438\u0432\u0438\u043b\u0435\u0433\u0438\u0440\u043e\u0432\u0430\u043d",
        )
        if ticker == "LSNGP"
        else None
    )
    return DividendEvent(
        status=status,
        event_type=event_type,
        amount_per_share=_amount(normalized),
        share_type=_share_type(normalized),
        period=_period(normalized),
        general_meeting_date=_date_after(
            normalized,
            r"\u043e\0431\u0449\u0435\u043c\u0443\s+\u0441\u043e\0431\u0440\u0430\u043d\u0438\u044e|\u0441\u043e\u0431\u0440\u0430\u043d\u0438\u0435",
        ),
        register_close_date=_date_after(
            normalized,
            r"\u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f\s+\u0440\u0435\u0435\u0441\u0442\u0440\u0430|\u0437\u0430\u043a\u0440\u044b\u0442\u044c\s+\u0440\u0435\u0435\u0441\u0442\u0440",
        ),
        policy_change=policy_change,
        board_recommendation=board,
        shareholder_decision=shareholder,
        rasbu_net_profit=rasbu_profit,
        dividend_base=dividend_base,
        preferred_share_payment=preferred_payment,
        source_url=source_url,
    )
