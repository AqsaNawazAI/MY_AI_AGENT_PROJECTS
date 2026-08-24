import os
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, RunConfig
from tools import search_information

# Load environment variables from .env file
load_dotenv()

# Define a structured output model for research results
class ResearchResult(BaseModel):
    topic: str
    summary: str
    key_points: list[str]
    sources: list[str]

async def main():
    # Create a research agent with instructions and tools
    research_agent = Agent(
        name="research_agent",
        instructions="""You are a helpful research assistant. 
        Your goal is to provide comprehensive and accurate information on any topic.
        Use the search_information tool to gather data, then synthesize it into a clear summary.
        Always provide structured output with the topic, summary, key points, and sources.""",
        tools=[search_information],
        output_type=ResearchResult,
    )
    
    # Get user input
    user_query = input("What topic would you like to research? ")
    
    # Configure the agent run
    config = RunConfig(run_name="research_session")
    
    # Run the agent
    result = await Runner.run(
        research_agent,
        [user_query],
        run_config=config
    )
    
    # Display the structured output
    print("\nResearch Results:")
    print(f"Topic: {result.agent_output.topic}")
    print(f"Summary: {result.agent_output.summary}")
    print("\nKey Points:")
    for point in result.agent_output.key_points:
        print(f"- {point}")
    print("\nSources:")
    for source in result.agent_output.sources:
        print(f"- {source}")

if __name__ == "__main__":
    asyncio.run(main()) 