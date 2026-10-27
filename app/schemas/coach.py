from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CoachCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    material_id: int = Field(gt=0)
    goal: str = Field(min_length=1, max_length=500)
    minutes: int = Field(ge=5, le=120)


class CoachCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    revision: int = Field(ge=0)
    action: Literal["message", "answer", "finish"]
    message: str = Field(default="", max_length=2000)
    answer: Literal["A", "B", "C", "D"] | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "message" and not self.message:
            raise ValueError("请输入学习目标或问题")
        if self.action == "answer" and self.answer is None:
            raise ValueError("请选择一个答案")
        if self.action != "answer" and self.answer is not None:
            raise ValueError("当前操作不能包含答案")
        return self
