# Research Assistant Agent

This project demonstrates the use of OpenAI's Agents SDK to create a research assistant that can search for information, summarize content, and organize findings into a structured report.

## Features

- Research any topic using AI
- Get structured reports with key findings, sources, and follow-up questions
- View the full conversation history between the agent and tools
- Download research reports as JSON
- Log all agent activities for future reference

## Setup

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

2. Set your OpenAI API key as an environment variable:

```bash
export OPENAI_API_KEY=your_api_key_here
```

## Running the Application

### Command Line Version

To run the simple command-line version:

```bash
python super_simple_agent.py
```

### Streamlit UI Version

To run the Streamlit web interface:

```bash
streamlit run research_app.py
```

This will start a local web server and open the application in your default web browser.

## How It Works

The application uses three main tools:

1. `search_web`: Simulates searching the web for information (mock implementation)
2. `summarize_text`: Simulates summarizing long text content (mock implementation)
3. `save_research_note`: Saves research notes (prints to console in this demo)

The agent uses these tools to gather information and then structures it into a comprehensive research report.

## Logging

All agent activities are logged to `agent_logs.log`. You can view these logs in the Streamlit UI sidebar or directly in the file. 