import streamlit as st
import asyncio
import json
import logging
from datetime import datetime
from agents import Agent, Runner, function_tool
from super_simple_agent import research_agent, run_research
import os
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("agent_logs.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("research_agent")

# Set up the Streamlit page
st.set_page_config(page_title="Research Assistant", page_icon="🔍", layout="wide")
st.title("Research Assistant")

# Display current date
current_date = datetime.now().strftime("%B %d, %Y")
st.caption(f"Today's date: {current_date}")

st.markdown("Enter a topic to research and get a comprehensive report.")

# Initialize session state for follow-up questions
if 'new_research_topic' not in st.session_state:
    st.session_state.new_research_topic = ""
if 'trigger_research' not in st.session_state:
    st.session_state.trigger_research = False
if 'research_history' not in st.session_state:
    st.session_state.research_history = []

# Create a form for user input
with st.form("research_form", clear_on_submit=st.session_state.trigger_research):
    # If a follow-up question was clicked, use it as the default value
    default_topic = st.session_state.new_research_topic if st.session_state.trigger_research else ""
    research_topic = st.text_input("Research Topic", value=default_topic, placeholder="Enter a topic to research...")
    
    # Add model selection dropdown
    model_options = ["gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
    selected_model = st.selectbox("Select AI Model", model_options, index=0)
    
    submit_button = st.form_submit_button("Research")
    
    # Reset the trigger after form is rendered
    if st.session_state.trigger_research:
        st.session_state.trigger_research = False

# Function to run the research agent and handle the async operation
def run_research_task(topic, model="gpt-4"):
    logger.info(f"Starting research on topic: {topic} using model: {model}")
    
    async def run_and_capture():
        try:
            result = await run_research(topic, model)
            logger.info(f"Research completed for topic: {topic}")
            return result
        except Exception as e:
            logger.error(f"Error during research: {str(e)}")
            raise e
    
    return asyncio.run(run_and_capture())

# Process the form submission
if submit_button and research_topic:
    # Add to research history if not already there
    if research_topic not in st.session_state.research_history:
        st.session_state.research_history.append(research_topic)
    
    # Display research chain if this is a follow-up question
    if len(st.session_state.research_history) > 1:
        st.markdown("### Research Chain")
        chain = " → ".join([f"**{topic}**" for topic in st.session_state.research_history])
        st.markdown(chain)
        st.divider()
    
    with st.spinner(f"Researching '{research_topic}' using {selected_model}... This may take a minute."):
        try:
            # Create a placeholder for the progress
            progress_placeholder = st.empty()
            progress_placeholder.info(f"Starting research process with {selected_model}...")
            
            # Run the research with the selected model
            result = run_research_task(research_topic, selected_model)
            
            # Log the result
            result_data = {
                'title': result.final_output.title,
                'summary': result.final_output.summary,
                'key_findings_count': len(result.final_output.key_findings),
                'sources_count': len(result.final_output.sources),
                'follow_up_questions_count': len(result.final_output.follow_up_questions) if result.final_output.follow_up_questions else 0
            }
            logger.info(f"Research result: {json.dumps(result_data)}")
            
            # Display the result in a nice format
            st.success("Research completed!")
            
            # Create tabs for different sections of the report
            tab1, tab2, tab3, tab4 = st.tabs(["Summary", "Key Findings", "Sources", "Follow-up Questions"])
            
            with tab1:
                st.header(result.final_output.title)
                st.write(result.final_output.summary)
            
            with tab2:
                for i, finding in enumerate(result.final_output.key_findings, 1):
                    st.markdown(f"**{i}.** {finding}")
            
            with tab3:
                st.subheader("Research Sources")
                if result.final_output.sources:
                    for i, source in enumerate(result.final_output.sources, 1):
                        # Check if the source contains a URL
                        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', source)
                        
                        if urls:
                            # Extract the URL and make it clickable
                            url = urls[0]
                            # Remove the URL from the display text to avoid duplication
                            display_text = source.replace(url, "").strip()
                            if display_text.endswith(":"):
                                display_text = display_text[:-1]
                            
                            st.markdown(f"**{i}.** {display_text} [{url}]({url})")
                        else:
                            st.markdown(f"**{i}.** {source}")
                else:
                    st.info("No sources provided in the research.")
            
            with tab4:
                if result.final_output.follow_up_questions:
                    st.markdown("Click on any question to research it further:")
                    for i, question in enumerate(result.final_output.follow_up_questions, 1):
                        # Create a button that looks like text for each follow-up question
                        if st.button(f"{i}. {question}", key=f"follow_up_{i}"):
                            st.session_state.new_research_topic = question
                            st.session_state.trigger_research = True
                            st.experimental_rerun()
                else:
                    st.info("No follow-up questions provided.")
            
            # Add a download button for the report
            report_data = {
                "title": result.final_output.title,
                "summary": result.final_output.summary,
                "key_findings": result.final_output.key_findings,
                "sources": result.final_output.sources,
                "follow_up_questions": result.final_output.follow_up_questions,
                "research_date": datetime.now().strftime("%B %d, %Y"),
                "research_topic": research_topic,
                "model_used": selected_model
            }
            
            st.download_button(
                label="Download Report as JSON",
                data=json.dumps(report_data, indent=2),
                file_name=f"research_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
            
            # Display the full conversation history in an expander
            with st.expander("View Agent Conversation History"):
                if hasattr(result, 'items'):
                    # New structure uses 'items' instead of 'messages'
                    for i, item in enumerate(result.items):
                        if hasattr(item, 'role') and hasattr(item, 'content'):
                            role = item.role.capitalize() if hasattr(item, 'role') else "Unknown"
                            content = item.content or "No content"
                            
                            if role == "Assistant" and hasattr(item, 'tool_calls') and item.tool_calls:
                                st.markdown(f"**{role}** (Tool Call):")
                                for tool_call in item.tool_calls:
                                    st.code(f"Tool: {tool_call.function.name}\nArguments: {tool_call.function.arguments}")
                            elif hasattr(item, 'name') and item.name:
                                st.markdown(f"**Tool Response** ({item.name}):")
                                st.code(content)
                            else:
                                st.markdown(f"**{role}**:")
                                st.write(content)
                            
                            if i < len(result.items) - 1:
                                st.divider()
                else:
                    st.info("Conversation history not available in this format.")
            
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            logger.error(f"Error displaying results: {str(e)}")

# Add some helpful information in the sidebar
with st.sidebar:
    st.header("About")
    st.markdown("""
    This Research Assistant uses AI to:
    
    1. Search for information on your topic
    2. Summarize and analyze the findings
    3. Organize the research into a structured report
    4. Suggest follow-up questions for further exploration
    
    All research activities are logged for future reference.
    """)
    
    # Add research history section
    if st.session_state.research_history:
        st.header("Research History")
        st.markdown("Click on a previous topic to research it again:")
        for i, topic in enumerate(st.session_state.research_history):
            if st.button(f"{topic}", key=f"history_{i}"):
                st.session_state.new_research_topic = topic
                st.session_state.trigger_research = True
                st.experimental_rerun()
        
        # Add clear history button
        if st.button("Clear History", key="clear_history"):
            st.session_state.research_history = []
            st.experimental_rerun()
    
    st.header("Model Selection")
    st.markdown("""
    You can choose from different AI models for your research:
    
    - **GPT-4**: Powerful general-purpose model with strong reasoning
    - **GPT-4o**: OpenAI's latest multimodal model with improved capabilities
    - **GPT-4o-mini**: Smaller, faster version of GPT-4o
    - **GPT-3.5-Turbo**: Faster but less powerful than GPT-4 models
    
    Different models may produce different research results and have varying response times.
    """)
    
    # Add OpenAI API key input for web search
    st.header("Web Search Configuration")
    api_key = st.text_input("OpenAI API Key (for web search)", type="password")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        st.success("API key set! Web search is now available.")
    else:
        st.warning("Please enter your OpenAI API key to enable web search functionality.")
    
    # Show log file in expander
    with st.expander("View Logs"):
        try:
            with open("agent_logs.log", "r") as f:
                log_content = f.read()
                st.code(log_content)
        except FileNotFoundError:
            st.info("No logs available yet.") 