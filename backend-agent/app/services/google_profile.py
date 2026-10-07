"""Read name, gender, and date of birth from the Google People API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GOOGLE_PEOPLE_URL = "https://people.googleapis.com/v1/people/me"
GOOGLE_PERSON_FIELDS = "names,genders,birthdays"

GENDER_VALUES = frozenset({"male", "female", "other"})
_GENDER_ALIASES = {
    "male": "male",
    "man": "male",
    "m": "male",
    "female": "female",
    "woman": "female",
    "f": "female",
    "other": "other",
    "non-binary": "other",
    "nonbinary": "other",
}


@dataclass(frozen=True)
class GooglePersonFacts:
    name: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None


def normalize_gender(value: str | None) -> str | None:
    if not value:
        return None
    mapped = _GENDER_ALIASES.get(value.strip().lower())
    if mapped in GENDER_VALUES:
        return mapped
    return None


def _primary_item(items: list[Any]) -> dict[str, Any] | None:
    records = [item for item in items if isinstance(item, dict)]
    if not records:
        return None
    for item in records:
        metadata = item.get("metadata")
        if isinstance(metadata, dict) and metadata.get("primary"):
            return item
    return records[0]


def parse_google_person(payload: dict[str, Any]) -> GooglePersonFacts:
    name = None
    names = payload.get("names")
    primary_name = _primary_item(names) if isinstance(names, list) else None
    if primary_name is not None:
        display = primary_name.get("displayName")
        if isinstance(display, str) and display.strip():
            name = display.strip()

    gender = None
    genders = payload.get("genders")
    primary_gender = _primary_item(genders) if isinstance(genders, list) else None
    if primary_gender is not None:
        raw = primary_gender.get("value")
        if isinstance(raw, str):
            gender = normalize_gender(raw)

    date_of_birth = _parse_birthday(payload.get("birthdays"))
    return GooglePersonFacts(name=name, gender=gender, date_of_birth=date_of_birth)


def _parse_birthday(birthdays: Any) -> date | None:
    if not isinstance(birthdays, list):
        return None
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in birthdays:
        if not isinstance(item, dict):
            continue
        raw_date = item.get("date")
        if not isinstance(raw_date, dict):
            continue
        year, month, day = raw_date.get("year"), raw_date.get("month"), raw_date.get("day")
        if not year or not month or not day:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source = metadata.get("source") if isinstance(metadata.get("source"), dict) else {}
        source_type = source.get("type")
        score = 0
        if source_type == "ACCOUNT":
            score += 2
        if metadata.get("primary"):
            score += 1
        ranked.append((score, raw_date))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    chosen = ranked[0][1]
    try:
        return date(int(chosen["year"]), int(chosen["month"]), int(chosen["day"]))
    except (TypeError, ValueError, OverflowError):
        return None


async def fetch_google_person(access_token: str) -> GooglePersonFacts:
    token = access_token.strip()
    if not token:
        return GooglePersonFacts()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                GOOGLE_PEOPLE_URL,
                params={"personFields": GOOGLE_PERSON_FIELDS},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        logger.warning("google people request failed")
        return GooglePersonFacts()
    if response.status_code != 200:
        logger.info("google people lookup status=%s", response.status_code)
        return GooglePersonFacts()
    try:
        payload = response.json()
    except ValueError:
        logger.info("google people lookup returned non-json")
        return GooglePersonFacts()
    if not isinstance(payload, dict):
        return GooglePersonFacts()
    return parse_google_person(payload)
