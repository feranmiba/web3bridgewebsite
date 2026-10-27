from __future__ import annotations

import re

from django.apps import apps


def _normalize_roman_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return token
    return token.upper()


def normalize_cohort_label(raw_label: str | None) -> str | None:
    """
    Canonicalize cohort labels while preserving non-cohort labels.

    Examples:
    - "cohort xv" -> "Cohort XV"
    - "master class cohort iii" -> "Master Class Cohort III"
    """
    label = (raw_label or "").strip()
    if not label:
        return None

    master_match = re.search(
        r"master\s*class\s*cohort\s*([ivxlcdm0-9]+)",
        label,
        flags=re.IGNORECASE,
    )
    if master_match:
        return f"Master Class Cohort {_normalize_roman_token(master_match.group(1))}"

    cohort_match = re.search(r"\bcohort\s*([ivxlcdm0-9]+)\b", label, flags=re.IGNORECASE)
    if cohort_match:
        return f"Cohort {_normalize_roman_token(cohort_match.group(1))}"

    if re.fullmatch(r"[ivxlcdm0-9]+", label, flags=re.IGNORECASE):
        return f"Cohort {_normalize_roman_token(label)}"

    return re.sub(r"\s+", " ", label).strip()


def _course_track_key(*, registration_name: str, cohort_label: str, course_name: str) -> str:
    text = " ".join(
        [
            (registration_name or "").lower(),
            (cohort_label or "").lower(),
            (course_name or "").lower(),
        ]
    )
    if "rust" in text or "master class" in text or "masterclass" in text:
        return "rust"
    if "zk" in text or "zero knowledge" in text:
        return "zk"
    if "web2" in text:
        return "web2"
    if "web3" in text or "solidity" in text:
        return "web3"
    return "generic"


def _registration_matches_track(registration, track_key: str) -> bool:
    if track_key == "generic":
        return True
    text = " ".join(
        [
            (registration.name or "").lower(),
            (registration.cohort or "").lower(),
        ]
    )
    if track_key == "rust":
        return ("rust" in text) or ("master class" in text) or ("masterclass" in text)
    if track_key == "zk":
        return ("zk" in text) or ("zero knowledge" in text)
    if track_key == "web2":
        return "web2" in text
    if track_key == "web3":
        return ("web3" in text) or ("solidity" in text)
    return True


def resolve_current_open_registration_ids() -> list[int]:
    """
    Active intake registration IDs: newest ``is_open`` programme per track (web3/web2/zk/rust).

    Older programmes often stay ``is_open=True`` in admin; this avoids pulling every
    historical paid row linked to any open registration.
    """
    registration_model = apps.get_model("cohort", "Registration")
    open_regs = list(
        registration_model.objects.filter(is_open=True).order_by("-updated_at", "-id")
    )
    if not open_regs:
        return []

    chosen_ids: list[int] = []
    seen_tracks: set[str] = set()
    for registration in open_regs:
        track_key = _course_track_key(
            registration_name=registration.name or "",
            cohort_label=registration.cohort or "",
            course_name="",
        )
        if track_key in seen_tracks:
            continue
        seen_tracks.add(track_key)
        chosen_ids.append(registration.id)
    return chosen_ids


def resolve_active_cohort_label(*, registration=None, course=None) -> str | None:
    """
    Resolve the cohort label from the current active intake when possible.

    Falls back to the linked registration label when no active peer is found.
    """
    linked_registration = registration
    if linked_registration is None and course is not None:
        linked_registration = getattr(course, "registration", None)
    if linked_registration is None:
        return None

    linked_label = normalize_cohort_label(
        linked_registration.cohort or linked_registration.name
    )
    track_key = _course_track_key(
        registration_name=linked_registration.name or "",
        cohort_label=linked_registration.cohort or "",
        course_name=getattr(course, "name", "") or "",
    )
    if track_key == "generic":
        return linked_label

    registration_model = apps.get_model("cohort", "Registration")
    active_registration = (
        registration_model.objects.filter(is_open=True)
        .order_by("-updated_at", "-id")
    )
    for reg in active_registration:
        if _registration_matches_track(reg, track_key):
            active_label = normalize_cohort_label(reg.cohort or reg.name)
            if active_label:
                return active_label
    return linked_label


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _token_to_int(token: str) -> int | None:
    token = (token or "").strip().upper()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if any(char not in _ROMAN_VALUES for char in token):
        return None
    total = 0
    previous = 0
    for char in reversed(token):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total or None


def cohort_number(raw_label: str | None) -> int | None:
    """Numeric rank of a cohort label. ``Cohort XIV``, ``xiv``, and ``Cohort-14`` all work."""
    label = (raw_label or "").strip()
    if not label:
        return None
    master_match = re.search(
        r"master\s*class(?:\s*cohort)?\s*([ivxlcdm]+|\d+)",
        label,
        flags=re.IGNORECASE,
    )
    if master_match:
        return _token_to_int(master_match.group(1))
    cohort_match = re.search(
        r"cohort[\s\-]*([ivxlcdm]+|\d+)",
        label,
        flags=re.IGNORECASE,
    )
    if cohort_match:
        return _token_to_int(cohort_match.group(1))
    return _token_to_int(label)


def deactivate_stale_registrations() -> int:
    """
    Close open programmes whose cohort is older than the current one on the same track.

    Web3 Cohort XIV closes when Web3 Cohort XV is open. Web2 Cohort XV stays open,
    because it is a different track. Programmes in the same cohort number stay open together.
    """
    registration_model = apps.get_model("cohort", "Registration")
    grouped: dict[str, list] = {}
    for registration in registration_model.objects.filter(is_open=True):
        track_key = _course_track_key(
            registration_name=registration.name or "",
            cohort_label=registration.cohort or "",
            course_name="",
        )
        grouped.setdefault(track_key, []).append(registration)

    stale_ids: list[int] = []
    for registrations in grouped.values():
        numbers = [
            cohort_number(registration.cohort or registration.name)
            for registration in registrations
        ]
        ranked = [number for number in numbers if number is not None]
        if not ranked:
            continue
        current_number = max(ranked)
        for registration, number in zip(registrations, numbers):
            if number is not None and number < current_number:
                stale_ids.append(registration.pk)
    if not stale_ids:
        return 0
    return registration_model.objects.filter(pk__in=stale_ids, is_open=True).update(
        is_open=False
    )


def apply_listing_scope(
    queryset,
    *,
    scope: str | None,
    cohort: str | None,
    open_field: str,
    cohort_fields: tuple[str, ...],
):
    """
    Default lists are the current cohort only.

    ``scope=previous`` returns closed cohorts and leaves the current ones out.
    A ``cohort`` value is a request for that cohort alone, current or previous.
    """
    cohort = (cohort or "").strip()
    if cohort:
        return filter_by_cohort(queryset, cohort, *cohort_fields)
    if (scope or "current").strip().lower() == "previous":
        return queryset.filter(**{open_field: False})
    return queryset.filter(**{open_field: True})


def cohort_label_for_registration(registration) -> str | None:
    """
    Cohort label for one programme.

    Uses that registration's own ``cohort`` (or its name), not a different
    open intake of the same track.
    """
    if registration is None:
        return None
    raw = (getattr(registration, "cohort", None) or "").strip() or (
        getattr(registration, "name", None) or ""
    ).strip()
    return normalize_cohort_label(raw)


def fit_participant_cohort(label: str | None) -> str | None:
    if label is None:
        return None
    participant_model = apps.get_model("cohort", "Participant")
    max_len = participant_model._meta.get_field("cohort").max_length
    return label[:max_len]


def filter_by_cohort(queryset, raw: str | None, *fields: str):
    """
    Match a cohort query against one or more text fields.

    ``xv`` and ``Cohort XV`` hit the same rows. An empty query does not filter.
    """
    from django.db.models import Q

    label = (raw or "").strip()
    if not label or not fields:
        return queryset
    normalized = normalize_cohort_label(label)
    labels = {label}
    if normalized:
        labels.add(normalized)
    combined = Q()
    for field in fields:
        for item in labels:
            combined |= Q(**{f"{field}__iexact": item})
    return queryset.filter(combined)
