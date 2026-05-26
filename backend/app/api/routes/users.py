from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.db.models import UserProfile
from app.db.session import get_db
from app.schemas.user import UserProfileCreate, UserProfileRead

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
    existing_profile = await get_profile_for_current_user(db, current_user)
    if existing_profile is not None:
        existing_profile.name = payload.name
        existing_profile.location = payload.location
        existing_profile.mobile_number = payload.mobile_number
        existing_profile.email = current_user.email
        await db.commit()
        await db.refresh(existing_profile)
        return existing_profile

    profile = UserProfile(
        id=current_user.id,
        email=current_user.email,
        name=payload.name,
        location=payload.location,
        mobile_number=payload.mobile_number,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile
