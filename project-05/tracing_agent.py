import os
import asyncio
import json
from dotenv import load_dotenv
from agents import Agent, Runner, AgentRunConfig
from agents.tracing import add_trace_processor, TracingProcessor
from tools import search_information

# Load environment variables from .env file
load_dotenv()

# Define a custom tracing processor
class CustomTracingProcessor(TracingProcessor):
    def __init__(self, output_file="trace_output.json"):
        self.output_file = output_file
        self.traces = []
    
    async def process_trace(self, trace):
        # Store the trace
        self.traces.append(trace)
        
        # Write to file
        with open(self.output_file, "w") as f:
            json.dump(self.traces, f, indent=2)
        
        print(f"Trace saved to {self.output_file}")

async def main():
    # Create a custom tracing processor
    custom_processor = CustomTracingProcessor()
    
    # Register the custom processor
    add_trace_processor(custom_processor)
    
    # Create an agent
    tracing_agent = Agent(
        name="tracing_agent",
        instructions="""You are a helpful assistant that provides information.
        Use the search_information tool to gather data when needed.""",
        tools=[search_information],
    )
    
    # Get user input
    user_query = input("What would you like to know about? ")
    
    # Configure the agent run with tracing enabled
    config = AgentRunConfig(
        run_name="traced_session",
        tracing_disabled=False,
        trace_non_openai_generations=True,
    )
    
    # Run the agent
    result = await Runner.run(
        tracing_agent,
        [user_query],
        run_config=config
    )
    
    # Display the result
    print("\nResponse:")
    print("-" * 50)
    print(result.agent_output)
    print("-" * 50)
    
    print("\nTracing information has been saved to trace_output.json")

if __name__ == "__main__":
    asyncio.run(main()) 