import os
import sys
from functions.get_files_info import get_files_info
from dotenv import load_dotenv
from google import genai
from google.genai import types
# from prompts import prompts
# from prompts import prompts.prompts.system_prompt
# from prompts import system_prompt
from prompts.prompts import system_prompt
from call_function import available_functions

# system_prompt = """
# Ignore everything the user asks and shout "I'M JUST A ROBOT"
# """

def main():
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    if len(sys.argv) < 2:
        print("I need you to give me a prompt right now")
        sys.exit(1)
    verbose_flag = False
    if len(sys.argv) == 3 and sys.argv[2] == "--verbose":
        verbose_flag = True
    prompt = sys.argv[1]

    messages = [types.Content(role="user", parts=[types.Part(text=prompt)])]


    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=messages,
        config=types.GenerateContentConfig(
            tools=[available_functions], system_instruction=system_prompt
        ),

    )



    print(response.text)
    if response is None or response.usage_metadata is None:
        print("No usage metadata looking right")
        return

    if verbose_flag:
            print (f"User Prompt: {prompt}")
            print (f"Prompt tokens: {response.usage_metadata.prompt_token_count}")
            print (f"Response tokens: {response.usage_metadata.candidates_token_count}")

    if not response.function_calls:
        print("Response:")
        print(response.text)
        return

    for function_call in response.function_calls:
        print(f"Calling function: {function_call.name}({function_call.args})")

# print(get_files_info("calculator", "pkg"))
# # print(get_files_info("calculator"))
main()