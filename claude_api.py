from openai import OpenAI
import os
from dotenv import load_dotenv

#Load environment variables from .env file
load_dotenv()

#Initialize the Claude client using xAI's base URL and API key from .env
client = OpenAI(
    api_key=os.getenv("CLAUDE_API_KEY"),
    base_url="https://api.x.ai/v1"
)

#Getting Claude's benchmark for a weak subskill
def get_claude_benchmark(skill_name, subskill_name, level_name, score):

    #Claude prompt
    prompt = f"""
    A learner scored {score}% on {subskill_name} in a {skill_name} assessment.
    Their current level is {level_name}.
    
    List the 5 most important {subskill_name} concepts a {level_name} level 
    {skill_name} professional must master to improve.
    
    Format your response as a simple numbered list. Be concise and specific.
    Do not include any introduction or conclusion, just the numbered list.
    """

    try:
        #Calling the Claude API
        response = client.chat.completions.create(
            model="claude-sonnet-5",
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

        #Extracting the text response from Claude
        claude_response = response.choices[0].message.content.strip()

        #final recommendation from claude
        recommendation = f"Score: {score}% — Key concepts to master in {subskill_name}:\n{claude_response}"

        return recommendation

    except Exception as e:
        #Just incase claude fails
        print(f"Claude API call failed for {subskill_name}: {e}")
        return f"Dedicate focused time to {subskill_name}. Significant improvement needed (score: {score}%)"


#testing if claude api is working
if __name__ == "__main__":
    result = get_claude_benchmark(
        skill_name="Frontend Web Development",
        subskill_name="JavaScript",
        level_name="JUNIOR",
        score=35
    )
    print("\nCLAUDE RECOMMENDATION:")
    print(result)
