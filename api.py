from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.learner_service import (
    register_learner, get_behavioural_questions,
    submit_behavioural_answers
)
from app.services.attempt_service import start_attempt
from app.services.scoring_service import submit_and_score, generate_recommendations, SubmitError
from app.repositories.recommendation_repo import get_learning_pathway
from app.models.models import Learner, Skill
from sqlalchemy import select

app = FastAPI(
    title="Tech Skill Assessment API",
    description="API for testing learners across 50 tech and revenue skills and generating learning pathways",
    version="2.0.0"
)

#The API router from the v1 module that contains all the endpoints for the application.
from app.api.v1.router import api_router
app.include_router(api_router)

#DATA MODELS: This defines what each endpoint expects

#Register Learner
class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str

#Start Test Attempt. It allows learners to declares their level before taking the test
class StartAttemptRequest(BaseModel):
    learner_id: int
    skill_id: int
    declared_level: str  #Learner's self-declared level e.g BEGINNER, JUNIOR, MID, ADVANCED

#A single answer submitted by the learner
class AnswerItem(BaseModel):
    question_id: int
    selected_option_id: int

#Submit Answers Request
class SubmitRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: List[AnswerItem]

#Behavioural Answer... A single behavioural answer submitted by the learner
class BehaviouralAnswerItem(BaseModel):
    question_id: int
    answer_text: str

#Behavioural Answers Request
class BehaviouralAnswersRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: List[BehaviouralAnswerItem]


#ENDPOINTS

#Register Learner
@app.post("/api/register")
async def learner_register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        #Register learner using the learner service
        learner_id = await register_learner(
            db=db,
            full_name=data.full_name,
            email=data.email,
            phone=data.phone
        )
        return {
            "status": "Success",
            "learner_id": learner_id,
            "message": f"Learner {data.full_name} registered successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Get Behavioural Questions for a specific skill
@app.get("/api/behavioural-questions/{skill_id}")
async def behavioural_questions(skill_id: int, db: AsyncSession = Depends(get_db)):
    try:
        #Fetch behavioural questions using the learner service
        questions = await get_behavioural_questions(db=db, skill_id=skill_id)
        if not questions:
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
        return {
            "status": "Success",
            "data": questions,
            "message": f"Behavioural questions retrieved for skill_id={skill_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Submit Behavioural Answers
@app.post("/api/behavioural-answers")
async def behavioural_answers(data: BehaviouralAnswersRequest, db: AsyncSession = Depends(get_db)):
    try:
        #Convert list of BehaviouralAnswerItem objects to plain dictionaries
        answers = [
            {
                "question_id": item.question_id,
                "answer_text": item.answer_text
            }
            for item in data.answers
        ]
        #Save answers using the learner service
        result = await submit_behavioural_answers(
            db=db,
            learner_id=data.learner_id,
            attempt_id=data.attempt_id,
            answers=answers
        )
        return {
            "status": "Success",
            "result": result,
            "message": f"Behavioural answers saved for learner_id={data.learner_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Start Test Attempt
@app.post("/api/attempt/start")
async def start_test_attempt(data: StartAttemptRequest, db: AsyncSession = Depends(get_db)):
    try:
        #Start attempt using the attempt service
        attempt_data = await start_attempt(
            db=db,
            learner_id=data.learner_id,
            skill_id=data.skill_id,
            declared_level=data.declared_level
        )
        return {
            "status": "Success",
            "attempt_id": attempt_data["attempt_id"],
            "declared_level": attempt_data["declared_level"],
            "total_questions": attempt_data["total_questions"],
            "questions": attempt_data["questions"],
            "message": f"Test attempt started for learner_id={data.learner_id} on skill_id={data.skill_id} at {data.declared_level} level"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Submit Answers and Get Score
@app.post("/api/attempt/submit")
async def submit_answers(data: SubmitRequest, db: AsyncSession = Depends(get_db)):
    try:
        #Convert list of AnswerItem objects to plain dictionaries
        answers = [
            {
                "question_id": item.question_id,
                "selected_option_id": item.selected_option_id
            }
            for item in data.answers
        ]

        #Score the attempt using the scoring service
        final_result = await submit_and_score(
            db=db,
            attempt_id=data.attempt_id,
            learner_id=data.learner_id,
            answers=answers
        )

        #Generate recommendations after scoring
        recommendations = await generate_recommendations(
            db=db,
            attempt_id=data.attempt_id,
            learner_id=data.learner_id
        )

        return {
            "status": "Success",
            "result": final_result,
            "recommendations": recommendations,
            "message": f"Answers submitted and scored for attempt_id={data.attempt_id}"
        }
    except SubmitError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Get Learning Pathway
@app.get("/api/learning-pathway/{learner_id}/{skill_id}")
async def learning_pathway(learner_id: int, skill_id: int, db: AsyncSession = Depends(get_db)):
    try:
        #Fetch learning pathway using the recommendation repository
        pathway_rows = await get_learning_pathway(db=db, learner_id=learner_id, skill_id=skill_id)

        if not pathway_rows:
            raise HTTPException(status_code=404, detail="No learning pathway found for this learner and skill")

        #Format the pathway
        pathway = [
            {
                "priority": row.priority,
                "subskill_name": row.subskill_name,
                "percentage_score": float(row.percentage_score),
                "recommendation": row.recommendation_text
            }
            for row in pathway_rows
        ]

        return {
            "status": "Success",
            "learner_id": learner_id,
            "skill_id": skill_id,
            "learning_pathway": pathway,
            "message": f"Learning pathway retrieved for learner_id={learner_id} and skill_id={skill_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#confirming if API is running
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "message": "Tech Assessment API is running"}