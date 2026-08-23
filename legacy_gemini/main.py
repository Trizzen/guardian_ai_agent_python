"""Legacy Gemini/Star CLI, preserved from the pre-Sentinel repository entrypoint.

Run from the repository root with the optional legacy dependency installed:
`uv run --extra legacy-gemini python -m legacy_gemini.main "your prompt"`.
This path is not used by Jaza Sentinel v0.1.
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from call_function import available_functions, call_function
from prompts.prompts import system_prompt


def main():
    parser = argparse.ArgumentParser(description="AI Code Assistant")
    parser.add_argument("user_prompt", type=str, help="Prompt to send to Gemini")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)
    messages = [types.Content(role="user", parts=[types.Part(text=args.user_prompt)])]
    if args.verbose:
        print(f"User prompt: {args.user_prompt}\n")

    for iteration in range(20):
        response = generate_content(client, messages, args.verbose)

        if response is None:
            print("No response returned from Gemini.")
            return

        if response.candidates:
            for candidate in response.candidates:
                messages.append(candidate.content)

        if not response.function_calls:
            print("Final response:")
            print(response.text)
            return

        function_responses = []

        for function_call_part in response.function_calls:
            function_call_result = call_function(function_call_part, verbose=args.verbose)

            function_response_part = function_call_result.parts[0]
            function_response = function_response_part.function_response.response

            if args.verbose:
                print(f"-> {function_response}")

            function_responses.append(function_response_part)

        messages.append(types.Content(role="user", parts=function_responses))

    print("Maximum iterations reached without a final response.")
    sys.exit(1)


def generate_content(client, messages, verbose):
    config = types.GenerateContentConfig(
        tools=[available_functions],
        system_instruction=system_prompt,
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=messages,
            config=config,
        )
    except errors.ClientError as e:
        print("Gemini API client error.")
        print("This is usually quota, rate-limit, API key, or request validation related.")
        print(e)
        return None
    except errors.ServerError as e:
        print("Gemini API server error.")
        print("This is usually temporary model capacity or service availability.")
        print(e)
        return None

    if not response.usage_metadata:
        raise RuntimeError("Gemini API response appears to be malformed")

    if verbose:
        print(f"Prompt tokens: {response.usage_metadata.prompt_token_count}")
        print(f"Response tokens: {response.usage_metadata.candidates_token_count}")

    return response


if __name__ == "__main__":
    main()
