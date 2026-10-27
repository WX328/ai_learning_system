from pydantic import BaseModel,Field

class QuestionGenerateRequest(BaseModel):
    material_id:int = Field(
        gt=0,
        description="学习资料ID"
    )

    topic:str = Field(
        min_length=1,
        description="出题知识点或主题"
    )

    count:int = Field(
        default=1,
        ge=1,
        le=3,
        description="生成题目数量"
    )

    difficulty:int = Field(
        default=1,
        ge=1,
        le=5,
        description="题目难度：1-5"
    )

    topic_id:int | None = Field(
        default=None,
        gt=0,
        description="知识点ID；生成新题时必需，为空会被拒绝"
    )

class QuestionAIOutput(BaseModel):
    question: str = Field(
        min_length=1
    )

    option_a: str = Field(
        min_length=1
    )

    option_b: str = Field(
        min_length=1
    )

    option_c: str = Field(
        min_length=1
    )

    option_d: str = Field(
        min_length=1
    )

    answer: str = Field(
        pattern="^[ABCD]$"
    )

    explanation: str = Field(
        min_length=1
    )

    difficulty: int = Field(
        ge=1,
        le=5
    )

class QuestionResponse(BaseModel):
    id:int
    material_id:int
    topic_id:int | None = None
    question_type:str
    question:str

    option_a:str | None
    option_b:str | None
    option_c:str | None
    option_d:str | None

    difficulty:int


class QuestionAnswerRequest(BaseModel):
    answer:str = Field(
        pattern="^[ABCD]$",
        description="用户答案，只能是A、B、C、D"
    )

class QuestionAnswerResponse(BaseModel):
    question_id:int
    user_answer:str
    correct_answer:str
    is_correct:bool
    explanation:str | None
    earned_xp:int
    feedback:str
    feedback_source:str


class QuestionFeedbackResponse(BaseModel):
    feedback:str
    source:str
