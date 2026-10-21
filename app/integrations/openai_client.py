from openai import OpenAI

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# The OpenAI client is created on first use, and only when OPENAI_API_KEY is set.
# (Before, it was created at import time, so the whole API crashed on startup without a key.)
_client = None


def get_client():
    global _client
    if not settings.OPENAI_API_KEY:
        return None
    if _client is None:
        # Every outbound call has a timeout, so a slow OpenAI never hangs a request forever
        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
            max_retries=2,
        )
    return _client


# Plain recommendation used when OpenAI is not set up or the call fails
def fallback_recommendation(subskill_name, score):
    return f"Dedicate focused time to {subskill_name}. Significant improvement needed (score: {score}%)"


# The main function to get OpenAI's benchmark for a weak subskill
def get_ai_benchmark(skill_name, subskill_name, level_name, score):

    # The prompt to be sent to OpenAI
    prompt = f"""
    A learner scored {score}% on {subskill_name} in a {skill_name} assessment.
    Their current level is {level_name}.

    List the 5 most important {subskill_name} concepts a {level_name} level
    {skill_name} professional must master to improve.

    Format your response as a simple numbered list. Be concise and specific.
    Do not include any introduction or conclusion, just the numbered list.
    """

    # No key yet: skip OpenAI and use the plain recommendation
    client = get_client()
    if client is None:
        return fallback_recommendation(subskill_name, score)

    try:
        # Call the OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a technical education expert. You give concise, specific learning recommendations for tech professionals.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.7,
        )

        # Extract the text response from OpenAI
        ai_response = (response.choices[0].message.content or "").strip()

        # Build the final recommendation combining score context and OpenAI advice
        recommendation = (
            f"Score: {score}% — Key concepts to master in {subskill_name}:\n{ai_response}"
        )

        return recommendation

    except Exception as e:
        # If OpenAI API fails, fall back to generic message
        logger.warning("openai_call_failed", subskill=subskill_name, error=type(e).__name__)
        return fallback_recommendation(subskill_name, score)
