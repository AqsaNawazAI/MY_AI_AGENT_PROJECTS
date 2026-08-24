from agents import Agent, Runner, function_tool, ModelSettings
import asyncio
import json
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from openai import OpenAI
import re
from datetime import datetime

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Define research tools
@function_tool
def search_web(query: str) -> str:
    """
    Search the web for information on a given query using OpenAI's web search capability.
    """
    try:
        # Get today's date
        today = datetime.now().strftime("%B %d, %Y")
        
        # Use OpenAI's web search capability
        completion = client.chat.completions.create(
            model="gpt-4o-search-preview",  # Use the search-enabled model
            web_search_options={
                "search_context_size": "medium",  # Options: "low", "medium", "high"
            },
            messages=[{
                "role": "user",
                "content": f"Search for information about: {query}. Today's date is {today}. Provide a comprehensive summary of the search results with relevant facts and information, considering the current date for time-sensitive information."
            }]
        )
        
        # Extract the response content
        response = completion.choices[0].message.content
        
        # Debug: Print the full response object structure
        print(f"Search response for '{query}':")
        print(response)
        
        # Extract citations if available
        citations = []
        if hasattr(completion.choices[0].message, 'annotations'):
            print("Annotations found in response")
            for annotation in completion.choices[0].message.annotations:
                print(f"Annotation type: {annotation.type}")
                if annotation.type == "url_citation" and hasattr(annotation, 'url_citation'):
                    url = annotation.url_citation.url
                    title = annotation.url_citation.title
                    citations.append(f"- {title}: {url}")
                    print(f"Added citation: {title}: {url}")
        else:
            # Check if there are citations in the message content itself
            print("No annotations found, checking for citations in content")
            # Look for URLs in the content
            urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', response)
            if urls:
                for url in urls:
                    citations.append(f"- Source: {url}")
                    print(f"Extracted URL from content: {url}")
        
        # Add citations to the response if available
        if citations:
            response += "\n\nSources:\n" + "\n".join(citations)
            print(f"Added {len(citations)} citations to response")
        else:
            print("No citations found or extracted")
            
        return response
    except Exception as e:
        # Fallback to mock response if there's an error
        error_msg = str(e)
        print(f"Error using OpenAI web search: {error_msg}")
        return f"Found information about '{query}'. Here are the top results: [mock results - web search unavailable due to error: {error_msg}]"

@function_tool
def summarize_text(text: str, max_length: Optional[int] = None) -> str:
    """
    Summarize a long text to make it more digestible using OpenAI's API.
    
    Args:
        text: The text to summarize
        max_length: Optional maximum length for the summary (in words)
    """
    try:
        # Set default max_length if not provided
        if max_length is None:
            max_length = 200
        
        # Get today's date
        today = datetime.now().strftime("%B %d, %Y")
        
        # Use OpenAI to summarize the text
        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # Using a smaller model for summarization to save costs
            messages=[
                {
                    "role": "system",
                    "content": f"You are a text summarization assistant. Today's date is {today}. Summarize the following text in approximately {max_length} words or less. Focus on the key points and maintain the original meaning. Be aware of the current date when summarizing time-sensitive information."
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        )
        
        summary = completion.choices[0].message.content
        print(f"Summarized text from {len(text)} characters to {len(summary)} characters")
        return summary
    
    except Exception as e:
        # Fallback to simple truncation if API call fails
        print(f"Error using OpenAI for summarization: {str(e)}")
        truncated = text[:min(len(text), max_length * 5)]  # Rough estimate of chars per word
        return f"Summary (API failed, showing truncated text): {truncated}..."

@function_tool
def save_research_note(title: str, content: str, tags: Optional[List[str]] = None) -> str:
    """
    Save a research note to the research database.
    """
    if tags is None:
        tags = []
    
    # In a real implementation, this would save to a database
    note = {
        "title": title,
        "content": content,
        "tags": tags,
    }
    
    # Just print the note for demo purposes
    print(f"Saved research note: {json.dumps(note, indent=2)}")
    return f"Successfully saved research note: '{title}'"

# Define the output type for structured responses
class ResearchReport(BaseModel):
    """A structured research report."""
    title: str
    summary: str
    key_findings: List[str]
    sources: List[str]
    follow_up_questions: Optional[List[str]] = None

# Create the research agent
research_agent = Agent(
    name="Research Assistant",
    instructions="""
    You are a helpful research assistant. Your job is to:
    
    1. Help users find information on topics they're researching
    2. Summarize and analyze information
    3. Organize research findings
    4. Suggest follow-up questions or areas to explore
    
    Use the tools provided to search for information, summarize content, and save notes.
    
    IMPORTANT INSTRUCTIONS FOR WEB SEARCH:
    - The search_web tool connects to OpenAI's web search capability to find real-time information from the internet
    - When you receive search results, carefully analyze the information and extract key points
    - Pay special attention to the "Sources" section at the end of search results - these are citations
    - Always include these sources in your final report's "sources" section
    - When citing information in your summary or key findings, mention the source
    
    TIME AWARENESS:
    - You will be provided with the current date in your instructions
    - Consider this date when researching time-sensitive topics
    - For historical events, provide context about how much time has passed
    - For future predictions, be clear about the timeframe relative to the current date
    - Indicate when information might be outdated or speculative
    
    Provide comprehensive but concise answers based on the information you find.
    Always cite your sources when using information from web searches.
    
    When preparing a final research report, make sure to structure it properly with:
    - A clear, informative title that reflects the research topic
    - A concise summary that captures the main findings (2-3 paragraphs)
    - 5-10 key findings, each 1-2 sentences long
    - All sources used, properly formatted
    - 3-5 follow-up questions for further research
    """,
    tools=[search_web, summarize_text, save_research_note],
    output_type=ResearchReport
)

# Function to run the research agent
async def run_research(query: str, model: str = "gpt-4"):
    """Run the research agent with the given query and specified model.
    
    Args:
        query: The research topic to investigate
        model: The model to use (default: gpt-4)
    """
    # Get today's date
    today = datetime.now().strftime("%B %d, %Y")
    
    # Create a clone of the agent with the specified model
    agent_with_model = research_agent.clone(
        model=model  # Set the model directly
    )
    
    result = await Runner.run(
        agent_with_model, 
        input=f"Research the following topic: {query}\n\nToday's date is {today}. Please consider this when providing information that may be time-sensitive.",
        max_turns=10  # Limit the number of turns to avoid infinite loops
    )
    return result

# Example usage
async def main():
    research_topic = "quantum computing applications in medicine"
    result = await run_research(research_topic)
    print("\n=== FINAL RESEARCH REPORT ===")
    print(f"Title: {result.final_output.title}")
    print(f"Summary: {result.final_output.summary}")
    print("\nKey Findings:")
    for i, finding in enumerate(result.final_output.key_findings, 1):
        print(f"{i}. {finding}")
    print("\nSources:")
    for i, source in enumerate(result.final_output.sources, 1):
        print(f"{i}. {source}")
    if result.final_output.follow_up_questions:
        print("\nFollow-up Questions:")
        for i, question in enumerate(result.final_output.follow_up_questions, 1):
            print(f"{i}. {question}")

if __name__ == "__main__":
    asyncio.run(main())