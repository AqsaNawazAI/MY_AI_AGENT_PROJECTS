import os
import asyncio
from dotenv import load_dotenv
from agents import Agent, Runner
from tools import search_information

# Load environment variables from .env file
load_dotenv()

async def main():
    # Create a streaming agent
    streaming_agent = Agent(
        name="streaming_agent",
        instructions="""You are a helpful assistant that provides information in a conversational manner.
        Use the search_information tool to gather data when needed.
        Respond in a friendly, engaging way, breaking your response into smaller chunks for better readability.""",
        tools=[search_information],
    )
    
    # Get user input
    user_query = input("What would you like to know about? ")
    
    # Run the agent with streaming
    stream = Runner.run_streamed(streaming_agent, [user_query])
    
    print("\nStreaming response:")
    print("-" * 50)
    
    # Process streaming events
    async for event in stream.stream_events():
        if hasattr(event, 'delta') and event.delta:
            print(event.delta, end="", flush=True)
    
    print("\n" + "-" * 50)
    print("Stream completed")

if __name__ == "__main__":
    asyncio.run(main()) 