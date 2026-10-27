"""Onsite and online fees for courses and the programmes they belong to."""

from __future__ import annotations

from cohort.models import ParticipationMode

PARTICIPATION_MODES = (ParticipationMode.ONLINE, ParticipationMode.ONSITE)


def normalize_participation_mode(value) -> str | None:
    token = (value or "").strip().lower()
    if token in PARTICIPATION_MODES:
        return token
    return None


def offered_modes(course) -> list[str]:
    """
    Modes a course can be taken in.

    An empty venue list, or a list with no online/onsite values, means both
    modes are still offered. Otherwise only the listed modes are allowed.
    """
    raw = getattr(course, "venue", None) or []
    if not isinstance(raw, list):
        return list(PARTICIPATION_MODES)
    modes: list[str] = []
    for item in raw:
        mode = normalize_participation_mode(item)
        if mode and mode not in modes:
            modes.append(mode)
    if not modes:
        return list(PARTICIPATION_MODES)
    return modes


def _clean_fee(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolved_fees(*, course=None, registration=None) -> dict[str, str | None]:
    """
    Price for each mode.

    A fee set on the course wins. Otherwise the programme fee is used.
    ``registrationFee`` is the legacy single price when a mode-specific fee
    is blank.
    """

    def pick(mode: str) -> str | None:
        for source in (course, registration):
            if source is None:
                continue
            found = _clean_fee(getattr(source, f"{mode}_fee", None))
            if found:
                return found
        if registration is None:
            return None
        return _clean_fee(getattr(registration, "registrationFee", None))

    return {
        ParticipationMode.ONLINE: pick(ParticipationMode.ONLINE),
        ParticipationMode.ONSITE: pick(ParticipationMode.ONSITE),
    }


def fee_for_mode(*, mode, course=None, registration=None) -> str | None:
    normalized = normalize_participation_mode(mode)
    if normalized is None:
        return None
    return resolved_fees(course=course, registration=registration).get(normalized)
