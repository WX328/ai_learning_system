from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


COMMON_PASSWORDS = {
    "password123456789",
    "123456789012345",
    "qwerty123456789",
    "admin1234567890",
    "iloveyou12345678",
}


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=15, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_obvious_password(self):
        lowered = self.password.casefold()
        if lowered in COMMON_PASSWORDS or lowered == self.username.casefold() or len(set(lowered)) == 1:
            raise ValueError("密码过于常见，请使用更长且独特的密码短语")
        return self
