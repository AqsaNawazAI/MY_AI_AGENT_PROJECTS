import os
import asyncio
from dotenv import load_dotenv
from agents import Agent, Runner, AgentRunConfig
from agents.guardrail import InputGuardrail
from tools import search_information

# Load environment variables from .env file
load_dotenv()

# Define a simple guardrail function to check for appropriate topics
async def is_appropriate_topic(messages, context):
    inappropriate_topics = ["harmful", "illegal", "unethical"]
    
    # Check the last user message
    for message in reversed(messages):
        if message.get("role") == "user" and "content" in message:
            content = message["content"].lower()
            for topic in inappropriate_topics:
                if topic in content:
                    return False
            return True
    
    return True

async def main():
    # Create a guardrail
    topic_guardrail = InputGuardrail(
        guardrail_function=is_appropriate_topic,
        tripwire_config=lambda output: not output,  # Trigger if the function returns False
        error_message="I cannot respond to questions about inappropriate topics."
    )
    
    # Create an agent with guardrails
    guarded_agent = Agent(
        name="guarded_agent",
        instructions="""You are a helpful assistant that provides information on appropriate topics.
        Use the search_information tool to gather data when needed.""",
        tools=[search_information],
        input_guardrails=[topic_guardrail],
    )
    
    # Get user input
    user_query = input("What would you like to know about? ")
    
    # Configure the agent run
    config = AgentRunConfig(run_name="guarded_session")
    
    try:
        # Run the agent
        result = await Runner.run(
            guarded_agent,
            [user_query],
            run_config=config
        )
        
        # Display the result
        print("\nResponse:")
        print("-" * 50)
        print(result.agent_output)
        print("-" * 50)
        
    except Exception as e:
        print(f"\nGuardrail triggered: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 