from pydantic import BaseModel,Field

class LearningMaterialCreate(BaseModel):
    title:str = Field(
        min_length=1,
        max_length=200
    )

    content:str = Field(
        min_length=1, max_length=200_000
    )

    material_type:str = "text"

class TopicItem(BaseModel):
    name:str = Field(
        min_length=1,
        description="知识点名称"
    )

    description:str = Field(
        min_length=1,
        description="知识点说明"
    )

class TopicExtractionResponse(BaseModel):
    topics:list[TopicItem] = Field(
        min_length=1,
        description="学习资料里面中提取的知识点"
    )

class TopicResponse(BaseModel):
    id:int
    material_id:int
    name:str
    description:str
