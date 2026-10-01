#Tech Assessment Service

A production-grade backend API that tests learners across 50 tech and revenue-focused skills, scores them, assigns proficiency levels, and generates AI-powered personalised learning pathways.

##Tech Stack

- **Python** — Core language
- **FastAPI** — API framework
- **MySQL** — Database
- **SQLAlchemy** — ORM (coming in Phase 1)
- **OpenAI GPT-4o** — AI-powered recommendations
- **Alembic** — Database migrations (coming in Phase 1)

## Features
- Learner registration with duplicate detection
- Self-declared level testing (Beginner, Junior, Mid, Advanced)
- 25 targeted questions per declared level
- Automated scoring with pass/fail logic (60% threshold)
- Proficiency level assignment
- Performance analytics by difficulty and subskill
- Personalised AI-powered learning pathway generation
- Behavioural assessment questions (general + skill-specific)
- 6 REST API endpoints with auto-generated Swagger UI

## Project Structure
tech-assessment-service/
├── api.py # FastAPI routes and endpoints
├── main.py # Core business logic
├── database.py # Database connection layer
├── scoring_engine.py # Scoring and pass/fail logic
├── level_engine.py # Proficiency level assignment
├── recommendation_engine.py # Learning pathway generation
├── openai_engine.py # OpenAI API integration
├── tech_skill_assessment.sql # Database dump
├── .env.example # Environment variables template
├── requirements.txt # Python dependencies
└── README.md # This file


## Setup

**1. Clone the repository**
```bash
git clone https://github.com/Growth-Hub-Tech/tech-assessment-service.git
cd tech-assessment-service
```

**2. Create and activate virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your actual values
```

**5. Set up the database**
```bash
mysql -u root -p < tech_skill_assessment.sql
```

**6. Run the API**
```bash
uvicorn api:app --reload
```

**7. View API documentation**

Open your browser and go to http://127.0.0.1:8000/docs


## API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Register a new learner |
| GET | `/api/behavioural-questions/{skill_id}` | Get behavioural questions |
| POST | `/api/behavioural-answers` | Submit behavioural answers |
| POST | `/api/attempt/start` | Start a test attempt |
| POST | `/api/attempt/submit` | Submit answers and get results |
| GET | `/api/learning-pathway/{learner_id}/{skill_id}` | Get learning pathway |

## Environment Variables
| Variable | Description |
|----------|-------------|
| `DB_HOST` | Database host address |
| `DB_PORT` | Database port (default: 3306) |
| `DB_USER` | Database username |
| `DB_PASSWORD` | Database password |
| `DB_NAME` | Database name |
| `OPENAI_API_KEY` | OpenAI API key for AI recommendations |

###

## Built By
Joshua Mudana - AI/ML Engineer, GrowthHub/Salesplat