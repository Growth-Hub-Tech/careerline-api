from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from main import register_learner, start_attempt, submit_and_score
from recommendation_engine import generate_recommendations, get_learning_pathway

app = FastAPI(
    title="Tech Skill Assessment API",
    description="API for testing learners across 50 tech and revenue skills and generating learning pathways",
    version="The Begining")

#Defining a data type to Register a Learner
class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str

#Start Test Attempt — learner declares their level before taking the test
class StartAttemptRequest(BaseModel):
    learner_id: int
    skill_id: int
    declared_level: str  #Learner's self-declared level e.g BEGINNER, JUNIOR, MID, ADVANCED

#Answer Item — a single answer submitted by the learner
class AnswerItem(BaseModel):
    question_id: int
    selected_option_id: int

#Submit Answers Request
class SubmitRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: List[AnswerItem]

#BUILDING ENDPOINTS TO REGISTER LEARNER, START TEST ATTEMPT, SUBMIT ANSWERS & SCORES, GET LEARNING PATHWAY

#Register Learner
@app.post("/api/register")
def learner_register(data: RegisterRequest):
    try:
        #Using the register_learner function from main.py
        learner_id = register_learner(
            full_name=data.full_name,
            email=data.email,
            phone=data.phone)
        #Return the response with the learner ID
        return {
            "status": "Success",
            "learner_id": learner_id,
            "message": f"Learner {data.full_name} registered successfully"}

    except Exception as e:
        #Return error if something goes wrong to avoid crashing
        raise HTTPException(status_code=500, detail=str(e))


#Start Test Attempt
@app.post("/api/attempt/start")
def start_test_attempt(data: StartAttemptRequest):
    try:
        attempt_data = start_attempt(
            learner_id=data.learner_id,
            skill_id=data.skill_id,
            declared_level=data.declared_level)

        return {
            "status": "Success",
            "attempt_id": attempt_data["attempt_id"],
            "declared_level": attempt_data["declared_level"],
            "total_questions": attempt_data["total_questions"],
            "questions": attempt_data["questions"],
            "message": f"Test attempt started for learner_id={data.learner_id} on skill_id={data.skill_id} at {data.declared_level} level"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Submit Answers and Get Score
@app.post("/api/attempt/submit")
def submit_answers(data: SubmitRequest):
    try:
        #Convert list of AnswerItem objects to plain dictionaries
        answers = [
            {
                "question_id": item.question_id,
                "selected_option_id": item.selected_option_id}
            for item in data.answers]

        #Calling submit_and_score from main.py
        final_result = submit_and_score(
            attempt_id=data.attempt_id,
            learner_id=data.learner_id,
            answers=answers)

        #Generating recommendations after scoring
        generate_recommendations(
            attempt_id=data.attempt_id,
            learner_id=data.learner_id)

        return {
            "status": "Success",
            "result": final_result,
            "message": f"Answers submitted and scored for attempt_id={data.attempt_id}"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#Get Learning Pathway
@app.get("/api/learning-pathway/{learner_id}/{skill_id}")
def learning_pathway(learner_id: int, skill_id: int):
    try:
        pathway = get_learning_pathway(learner_id, skill_id)
        return {
            "status": "Success",
            "learning_pathway": pathway,
            "message": f"Learning pathway retrieved for learner_id={learner_id} and skill_id={skill_id}"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))