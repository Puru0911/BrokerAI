from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.db.models import UserProfile
from app.db.session import get_db
from app.schemas.user import (
    GoogleProfileBootstrap,
    UserProfileCreate,
    UserProfilePatch,
    UserProfileRead,
)
from app.services.google_profile import fetch_google_person

router = APIRouter()


async def get_profile_for_current_user(
    db: AsyncSession,
    current_user: CurrentUser,
) -> UserProfile | None:
    profile = await db.get(UserProfile, current_user.id)
    if profile is not None:
        return profile

    if current_user.email:
        result = await db.execute(
            select(UserProfile).where(UserProfile.email == current_user.email)
        )
        return result.scalar_one_or_none()

    return None


async def upsert_user_profile(
    db: AsyncSession,
    current_user: CurrentUser,
    *,
    name: str,
    gender: str | None = None,
    date_of_birth: date | None = None,
    overwrite_name: bool = True,
) -> tuple[UserProfile, bool]:
    existing_profile = await get_profile_for_current_user(db, current_user)
    if existing_profile is not None:
        if overwrite_name:
            existing_profile.name = name
        if gender and not existing_profile.gender:
            existing_profile.gender = gender
        if date_of_birth and existing_profile.date_of_birth is None:
            existing_profile.date_of_birth = date_of_birth
        existing_profile.email = current_user.email
        await db.commit()
        await db.refresh(existing_profile)
        return existing_profile, False

    profile = UserProfile(
        id=current_user.id,
        email=current_user.email,
        name=name,
        location=None,
        mobile_number=None,
        gender=gender,
        date_of_birth=date_of_birth,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile, True


@router.get("/me", response_model=UserProfileRead)
async def get_my_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    profile = await get_profile_for_current_user(db, current_user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile has not been created",
        )
    return profile


@router.post("/me", response_model=UserProfileRead, status_code=status.HTTP_201_CREATED)
async def create_my_profile(
    payload: UserProfileCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    profile, _created = await upsert_user_profile(
        db,
        current_user,
        name=payload.name,
        gender=payload.gender,
        date_of_birth=payload.date_of_birth,
        overwrite_name=True,
    )
    return profile


@router.post("/me/google", response_model=UserProfileRead)
async def bootstrap_google_profile(
    payload: GoogleProfileBootstrap,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    google = (
        await fetch_google_person(payload.google_access_token)
        if payload.google_access_token
        else None
    )
    name = (payload.name or (google.name if google else None) or "").strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Google did not provide a name. Enter your profile details to continue.",
        )
    profile, _created = await upsert_user_profile(
        db,
        current_user,
        name=name,
        gender=google.gender if google else None,
        date_of_birth=google.date_of_birth if google else None,
        overwrite_name=False,
    )
    return profile


@router.patch("/me", response_model=UserProfileRead)
async def patch_my_profile(
    payload: UserProfilePatch,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    profile = await get_profile_for_current_user(db, current_user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile has not been created",
        )
    profile.notify_email = payload.notify_email
    await db.commit()
    await db.refresh(profile)
    return profile
