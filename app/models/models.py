from sqlalchemy import Integer, String, Text, Boolean, DateTime, Numeric, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum

#Changing the MySQL ENUM types to Python's versions

class LevelName(str, enum.Enum):
    BEGINNER = "BEGINNER"
    JUNIOR = "JUNIOR"
    MID = "MID"
    ADVANCED = "ADVANCED"

#Values are UPPERCASE on purpose: they must be exactly the labels of the Postgres
#enum types (created by Alembic and filled by migrate_data.py with .upper()).
#Name == value, and every Enum() column below stores the VALUE (values_callable),
#so Python and Postgres can never disagree again.
class AttemptStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    PASSED = "PASSED"
    FAILED = "FAILED"

class QuestionType(str, enum.Enum):
    GENERAL = "GENERAL"
    SKILL_SPECIFIC = "SKILL_SPECIFIC"

class LearnerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def pg_enum(enum_cls, name):
    """Postgres enum column that stores the Python enum's VALUE (not its name)."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])

#Creating model for ProficiencyLevel...(MoDel 1)
class ProficiencyLevel(Base):
    __tablename__ = "proficiency_level"

    level_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level_name: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False, unique=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

#Creating model for LevelThreshold....(Model 2)
class LevelThreshold(Base):
    __tablename__ = "level_threshold"

    threshold_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level_id: Mapped[int] = mapped_column(Integer, ForeignKey("proficiency_level.level_id"), nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)

#Creating model for Learner....(Model 3)
class Learner(Base):
    __tablename__ = "learner"

    learner_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    registration_date: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    learner_status: Mapped[LearnerStatus] = mapped_column(pg_enum(LearnerStatus, "learnerstatus"), default=LearnerStatus.ACTIVE)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

#Creating model for Skill....(Model 4)
class Skill(Base):
    __tablename__ = "skills"

    skill_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    skill_descr: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    #Relationship: one skill has many subskills
    subskills: Mapped[list["Subskill"]] = relationship("Subskill", back_populates="skill")


#Creating model for Subskill....(Model 5)
class Subskill(Base):
    __tablename__ = "subskills"

    subskill_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=False)
    subskill_name: Mapped[str] = mapped_column(String(100), nullable=False)

    #Relationship: one subskill belongs to one skill
    skill: Mapped["Skill"] = relationship("Skill", back_populates="subskills")
    #Relationship: one subskill has many questions
    questions: Mapped[list["Question"]] = relationship("Question", back_populates="subskill")


#Creating model for Question....(Model 6)
class Question(Base):
    __tablename__ = "questions"

    question_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subskill_id: Mapped[int] = mapped_column(Integer, ForeignKey("subskills.subskill_id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty_level: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    #Relationship: one question belongs to one subskill
    subskill: Mapped["Subskill"] = relationship("Subskill", back_populates="questions")
    #Relationship: one question has many options
    options: Mapped[list["Option"]] = relationship("Option", back_populates="question")


#Creating model for Option....(Model 7)
class Option(Base):
    __tablename__ = "options"

    option_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.question_id"), nullable=False)
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    #Relationship: one option belongs to one question
    question: Mapped["Question"] = relationship("Question", back_populates="options")


#Creating model for TestAttempt....(Model 8)
class TestAttempt(Base):
    __tablename__ = "test_attempt"

    attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(Integer, ForeignKey("learner.learner_id"), nullable=False)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=False)
    declared_level_id: Mapped[int] = mapped_column(Integer, ForeignKey("proficiency_level.level_id"), nullable=True)
    start_time: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    end_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    overall_percentage: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00)
    assigned_level_id: Mapped[int] = mapped_column(Integer, ForeignKey("proficiency_level.level_id"), nullable=True)
    attempt_status: Mapped[AttemptStatus] = mapped_column(pg_enum(AttemptStatus, "attemptstatus"), default=AttemptStatus.IN_PROGRESS)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


#Creating model for LearnerAnswer....(Model 9)
class LearnerAnswer(Base):
    __tablename__ = "learner_answer"

    learner_answer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.question_id"), nullable=False)
    selected_option_id: Mapped[int] = mapped_column(Integer, ForeignKey("options.option_id"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answered_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


#Creating model for LearnerLevel....(Model 10)
class LearnerLevel(Base):
    __tablename__ = "learner_level"

    learner_level_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(Integer, ForeignKey("learner.learner_id"), nullable=True)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=True)
    level_id: Mapped[int] = mapped_column(Integer, ForeignKey("proficiency_level.level_id"), nullable=True)
    assigned_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


#Creating model for AttemptDifficultyScore....(Model 11)
class AttemptDifficultyScore(Base):
    __tablename__ = "attempt_difficulty_score"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=False)
    difficulty_level: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00)


#Creating model for AttemptSubskillScore....(Model 12)
class AttemptSubskillScore(Base):
    __tablename__ = "attempt_subskill_score"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=False)
    subskill_id: Mapped[int] = mapped_column(Integer, ForeignKey("subskills.subskill_id"), nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00)


#Creating model for SubskillRecommendation....(Model 13)
class SubskillRecommendation(Base):
    __tablename__ = "subskill_recommendation"

    recommendation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=False)
    learner_id: Mapped[int] = mapped_column(Integer, ForeignKey("learner.learner_id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00)
    subskill_id: Mapped[int] = mapped_column(Integer, ForeignKey("subskills.subskill_id"), nullable=False)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


#Creating model for BehaviouralQuestion....(Model 14)
class BehaviouralQuestion(Base):
    __tablename__ = "behavioural_questions"

    question_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(pg_enum(QuestionType, "questiontype"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


#Creating model for LearnerProfile....(Model 15)
class LearnerProfile(Base):
    __tablename__ = "learner_profile"

    profile_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(Integer, ForeignKey("learner.learner_id"), nullable=False)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id"), nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("behavioural_questions.question_id"), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

#Which questions were served in an attempt (used to validate the submitted answers)
class AttemptQuestion(Base):
    __tablename__ = "attempt_question"

    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("test_attempt.attempt_id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.question_id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
