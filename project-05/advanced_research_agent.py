import os
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, AgentRunConfig
from tools import search_information, save_finding, get_findings, ResearchContext

# Load environment variables from .env file
load_dotenv()

# Define a structured output model for research results
class ResearchResult(BaseModel):
    topic: str
    summary: str
    key_points: list[str]
    sources: list[str]

async def main():
    # Create a research context
    research_context = ResearchContext()
    
    # Create a research agent with instructions and tools
    research_agent = Agent(
        name="advanced_research_agent",
        instructions="""You are an advanced research assistant with memory capabilities.
        Your goal is to provide comprehensive and accurate information on any topic.
        
        Use the following tools:
        - search_information: To gather data on a topic
        - save_finding: To save important findings to your memory
        - get_findings: To retrieve previously saved findings
        
        As you research, save important findings using the save_finding tool.
        You can retrieve your findings at any time using the get_findings tool.
        
        Always provide structured output with the topic, summary, key points, and sources.""",
        tools=[search_information, save_finding, get_findings],
        output_type=ResearchResult,
        context_type=ResearchContext,
    )
    
    # Get user input
    user_query = input("What topic would you like to research? ")
    
    # Configure the agent run
    config = AgentRunConfig(run_name="advanced_research_session")
    
    # Run the agent
    result = await Runner.run(
        research_agent,
        [user_query],
        context=research_context,
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
    
    # Display saved findings
    print("\nSaved Findings:")
    print(get_findings(research_context))

if __name__ == "__main__":
    asyncio.run(main()) 