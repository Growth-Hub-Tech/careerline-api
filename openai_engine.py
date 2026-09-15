from openai import OpenAI
import os
from dotenv import load_dotenv

#Load environment variables from .env file
load_dotenv()

#Initialize the OpenAI client using API key from .env
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

#The main function to get OpenAI's benchmark for a weak subskill
def get_ai_benchmark(skill_name, subskill_name, level_name, score):

    #The prompt to be sent to OpenAI
    prompt = f"""
    A learner scored {score}% on {subskill_name} in a {skill_name} assessment.
    Their current level is {level_name}.
    
    List the 5 most important {subskill_name} concepts a {level_name} level 
    {skill_name} professional must master to improve.
    
    Format your response as a simple numbered list. Be concise and specific.
    Do not include any introduction or conclusion, just the numbered list.
    """

    try:
        #Call the OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a technical education expert. You give concise, specific learning recommendations for tech professionals."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=300,
            temperature=0.7
        )

        #Extract the text response from OpenAI
        ai_response = response.choices[0].message.content.strip()

        #Build the final recommendation combining score context and OpenAI advice
        recommendation = f"Score: {score}% — Key concepts to master in {subskill_name}:\n{ai_response}"

        return recommendation

    except Exception as e:
        #If OpenAI API fails, fall back to generic message
        print(f"[WARN] OpenAI API call failed for {subskill_name}: {e}")
        return f"Dedicate focused time to {subskill_name}. Significant improvement needed (score: {score}%)"


#TEST
if __name__ == "__main__":
    result = get_ai_benchmark(
        skill_name="Frontend Web Development",
        subskill_name="JavaScript",
        level_name="JUNIOR",
        score=35
    )
    print("\n===== AI BENCHMARK =====")
    print(result)
    print("========================")