from __future__ import annotations

from datetime import date

from app.schemas.user import UserProfileCreate
from app.services.google_profile import normalize_gender, parse_google_person


def test_parse_google_person_reads_primary_name_gender_and_account_birthday() -> None:
    facts = parse_google_person(
        {
            "names": [
                {"displayName": "Other Name"},
                {
                    "metadata": {"primary": True},
                    "displayName": "Ada Lovelace",
                },
            ],
            "genders": [
                {
                    "metadata": {"primary": True},
                    "value": "female",
                }
            ],
            "birthdays": [
                {"date": {"month": 1, "day": 1}},
                {
                    "metadata": {
                        "primary": True,
                        "source": {"type": "ACCOUNT"},
                    },
                    "date": {"year": 1815, "month": 12, "day": 10},
                },
            ],
        }
    )
    assert facts.name == "Ada Lovelace"
    assert facts.gender == "female"
    assert facts.date_of_birth == date(1815, 12, 10)


def test_parse_google_person_ignores_birthday_without_year() -> None:
    facts = parse_google_person(
        {
            "names": [{"displayName": "Ada"}],
            "genders": [{"value": "unknown"}],
            "birthdays": [{"date": {"month": 5, "day": 15}}],
        }
    )
    assert facts.name == "Ada"
    assert facts.gender is None
    assert facts.date_of_birth is None


def test_normalize_gender_aliases() -> None:
    assert normalize_gender("Woman") == "female"
    assert normalize_gender("man") == "male"
    assert normalize_gender("non-binary") == "other"
    assert normalize_gender("prefer not to say") is None


def test_profile_create_accepts_identity_fields_without_mobile_or_location() -> None:
    payload = UserProfileCreate(
        name="  Ada Lovelace  ",
        gender="Woman",
        date_of_birth=date(1815, 12, 10),
    )
    assert payload.name == "Ada Lovelace"
    assert payload.gender == "female"
    assert payload.date_of_birth == date(1815, 12, 10)
    assert payload.location is None
    assert payload.mobile_number is None
