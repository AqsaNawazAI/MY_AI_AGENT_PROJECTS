import os
import asyncio
from dotenv import load_dotenv
from agents import Agent, Runner, handoff
from tools import search_information

# Load environment variables from .env file
load_dotenv()

async def main():
    # Create specialized agents
    science_agent = Agent(
        name="science_agent",
        instructions="""You are a science expert. Provide detailed, accurate information about scientific topics.
        Use the search_information tool to gather data when needed.
        Focus on scientific facts, theories, and explanations.""",
        tools=[search_information],
    )
    
    history_agent = Agent(
        name="history_agent",
        instructions="""You are a history expert. Provide detailed, accurate information about historical topics.
        Use the search_information tool to gather data when needed.
        Focus on historical events, figures, and contexts.""",
        tools=[search_information],
    )
    
    # Create a triage agent that can hand off to specialized agents
    triage_agent = Agent(
        name="triage_agent",
        instructions="""You are a helpful assistant that can triage questions to specialized agents.
        For science questions, hand off to the science_agent.
        For history questions, hand off to the history_agent.
        For general questions, answer directly.""",
        tools=[search_information],
        handoffs=[handoff(science_agent), handoff(history_agent)],
    )
    
    # Get user input
    user_query = input("What would you like to know about? ")
    
    # Run the triage agent
    result = await Runner.run(triage_agent, [user_query])
    
    # Display the result
    print("\nResponse:")
    print("-" * 50)
    print(result.agent_output)
    print("-" * 50)
    
    # Show which agent handled the query
    if result.handoff_history:
        print(f"This query was handled by: {result.handoff_history[-1].target_agent_name}")
    else:
        print("This query was handled by: triage_agent")

if __name__ == "__main__":
    asyncio.run(main()) 