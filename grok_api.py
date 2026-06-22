from openai import OpenAI
import os
from dotenv import load_dotenv

#Load environment variables from .env file
load_dotenv()

#Initialize the Grok client using xAI's base URL and API key from .env
client = OpenAI(
    api_key=os.getenv("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

#Getting Grok's benchmark for a weak subskill
def get_grok_benchmark(skill_name, subskill_name, level_name, score):

    #Grok prompt
    prompt = f"""
    A learner scored {score}% on {subskill_name} in a {skill_name} assessment.
    Their current level is {level_name}.
    
    List the 5 most important {subskill_name} concepts a {level_name} level 
    {skill_name} professional must master to improve.
    
    Format your response as a simple numbered list. Be concise and specific.
    Do not include any introduction or conclusion, just the numbered list.
    """

    try:
        #Calling the Grok API
        response = client.chat.completions.create(
            model="grok-3",
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

        #Extracting the text response from Grok
        grok_response = response.choices[0].message.content.strip()

        #final recommendation from grok
        recommendation = f"Score: {score}% — Key concepts to master in {subskill_name}:\n{grok_response}"

        return recommendation

    except Exception as e:
        #Just incase groke fails
        print(f"Grok API call failed for {subskill_name}: {e}")
        return f"Dedicate focused time to {subskill_name}. Significant improvement needed (score: {score}%)"


#testing if grok api is working
if __name__ == "__main__":
    result = get_grok_benchmark(
        skill_name="Frontend Web Development",
        subskill_name="JavaScript",
        level_name="JUNIOR",
        score=35
    )
    print("\nGROK RECOMMENDATION:")
    print(result)
