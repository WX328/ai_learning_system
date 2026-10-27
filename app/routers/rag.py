from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, LearningMaterial, QAHistory,Topic
from app.core.dependencies import get_current_user
from app.services.rag import rag_answer
from app.schemas.rag import RAGAskRequest, RAGAskResponse
from app.core.resource_limits import model_request_guard


router = APIRouter(
    prefix="/rag",
    tags=["RAG"]
)


@router.post(
    "/ask",
    response_model=RAGAskResponse, dependencies=[Depends(model_request_guard)]
)
def ask_question(
    request: RAGAskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. 检查学习资料是否存在，并且属于当前用户
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == request.material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=404,
            detail="学习资料不存在或无权访问"
        )

    # 2. 执行 RAG
    if request.topic_id is not None:
        topic = db.query(Topic).filter(
            Topic.id == request.topic_id,
            Topic.material_id == request.material_id
        ).first()

        if topic is None:
            raise HTTPException(
                status_code=404,
                detail="知识点不存在或不属于该学习资料"
            )

    rag_result = rag_answer(
        query=request.query,
        material_id=request.material_id,
        db=db,
        topic_id=request.topic_id
    )

    answer = rag_result["answer"]

    history_id = None

    # 3. 保存问答历史
    if rag_result["status"] == "answered":
        history = QAHistory(
            user_id=current_user.id,
            material_id=request.material_id,
            question=request.query,
            answer=answer
        )

        db.add(history)
        db.commit()
        db.refresh(history)

        history_id = history.id

    # 4. 返回结果
    return {
        "history_id": history_id,
        "question": request.query,
        "answer": answer,
        "status": rag_result["status"],
        "context_source": rag_result["context_source"],
        "sources": rag_result.get("sources", []),
        "retrieval": rag_result.get("retrieval"),
    }


@router.get("/history")
def get_qa_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    histories = db.query(QAHistory).filter(
        QAHistory.user_id == current_user.id
    ).order_by(
        QAHistory.created_at.desc()
    ).all()

    return histories
