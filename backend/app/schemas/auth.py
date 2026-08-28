from datetime import datetime
from typing import Literal
import unicodedata

from pydantic import BaseModel, Field, field_validator


EducationStage = Literal[
    "middle_school", "high_school", "undergraduate", "graduate", "working", "other",
]
CareerGoalStatus = Literal["exploring", "confirmed"]
AccountRole = Literal["user", "admin"]


_COMMON_PASSWORDS = frozenset({
    "123456789012345",
    "abcdefghijklmno",
    "adminadminadminadmin",
    "correct horse battery staple",
    "iloveyouiloveyou",
    "letmeinletmeinletmein",
    "password1234567",
    "qwertyuiopasdfgh",
})


def _password_lookup_key(password: str) -> str:
    normalized = unicodedata.normalize("NFKC", password).casefold()
    return " ".join(normalized.split())


def validate_new_password(password: str) -> str:
    if _password_lookup_key(password) in _COMMON_PASSWORDS:
        raise ValueError("密码过于常见，请使用更独特的长密码")
    return password


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=15, max_length=128)
    display_name: str = Field(min_length=1, max_length=40)
    education_stage: EducationStage
    background: str = Field(min_length=1, max_length=500)
    focus_areas: list[str] = Field(min_length=1, max_length=5)
    weekly_hours: int = Field(ge=1, le=80)
    preferred_modes: list[str] = Field(min_length=1, max_length=6)
    career_goal: str = Field(default="", max_length=200)
    career_goal_status: CareerGoalStatus = "exploring"

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_new_password(value)

    @field_validator("focus_areas", "preferred_modes")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip()[:50] for value in values if str(value).strip()]
        return list(dict.fromkeys(cleaned))

    @field_validator("career_goal_status")
    @classmethod
    def valid_career_status(cls, value: str, info):
        career_goal = str(info.data.get("career_goal") or "").strip()
        if value == "confirmed" and not career_goal:
            raise ValueError("确认职业理想前需要填写目标")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class AuthenticatedProfileResponse(BaseModel):
    education_stage: str
    background: str
    focus_areas: list[str]
    weekly_hours: int
    preferred_modes: list[str]
    career_goal: str
    career_goal_status: str


class AuthenticatedAccountResponse(BaseModel):
    id: int
    account_number: int
    username: str
    display_name: str
    learner_id: int
    role: AccountRole
    status: str
    must_change_password: bool
    is_legacy_demo: bool
    profile: AuthenticatedProfileResponse
    dev_test_login_enabled: bool
    is_dev_login: bool
    desktop_auth_token: str | None = None


class LogoutResponse(BaseModel):
    status: Literal["ok"]


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)

    @field_validator("new_password")
    @classmethod
    def strong_new_password(cls, value: str) -> str:
        return validate_new_password(value)


class CsrfTokenResponse(BaseModel):
    csrf_token: str


class ModelCredentialUpdateRequest(BaseModel):
    # Empty/whitespace means "keep the current encrypted key". Deletion is an
    # explicit DELETE so masked form submissions cannot erase a credential.
    api_key: str = Field(default="", max_length=4096)


class ModelCredentialMetadata(BaseModel):
    configured: bool
    key_hint: str = ""
    updated_at: datetime | None = None


class ModelCredentialTestRequest(BaseModel):
    base_url: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=200)


class ModelCredentialTestResponse(BaseModel):
    status: Literal["ok"]
    model: str
    latency_ms: int


class ModelCredentialResolveResponse(BaseModel):
    api_key: str
    key_hint: str
    version: int


class AdminAccountProjection(BaseModel):
    account_number: int
    username: str
    display_name: str
    role: AccountRole
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
    project_count: int = 0
    api_key_configured: bool = False


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    education_stage: EducationStage | None = None
    background: str | None = Field(default=None, min_length=1, max_length=500)
    focus_areas: list[str] | None = Field(default=None, min_length=1, max_length=5)
    weekly_hours: int | None = Field(default=None, ge=1, le=80)
    preferred_modes: list[str] | None = Field(default=None, min_length=1, max_length=6)
    career_goal: str | None = Field(default=None, max_length=200)
    career_goal_status: CareerGoalStatus | None = None


class MemoryArchiveRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
