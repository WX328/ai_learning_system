from pydantic import BaseModel,Field

class LearningRecordCreate(BaseModel):
    content_type:str
    content_id:int | None = None

    study_time:int = Field(
        default=0,
        ge=0
    )

    progress:int = Field(
        default=0,
        ge=0,
        le=100
    )