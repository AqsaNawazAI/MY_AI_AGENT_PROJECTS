from agents import function_tool
from agents.run_context import AgentContextWrapper
from typing import Dict, List, Any

class ResearchContext:
    def __init__(self):
        self.search_history: List[str] = []
        self.findings: Dict[str, Any] = {}

@function_tool
def save_finding(context: AgentContextWrapper[ResearchContext], topic: str, finding: str) -> str:
    """
    Save an important finding to the research context.
    
    Args:
        context: The agent context wrapper
        topic: The topic category for this finding
        finding: The important information to save
        
    Returns:
        A confirmation message
    """
    if topic not in context.agent_context.findings:
        context.agent_context.findings[topic] = []
    
    context.agent_context.findings[topic].append(finding)
    return f"Finding saved under topic '{topic}'"

@function_tool
def get_findings(context: AgentContextWrapper[ResearchContext], topic: str = None) -> str:
    """
    Retrieve findings from the research context.
    
    Args:
        context: The agent context wrapper
        topic: Optional topic to filter findings (if None, returns all findings)
        
    Returns:
        A string representation of the findings
    """
    if not context.agent_context.findings:
        return "No findings have been saved yet."
    
    if topic is not None:
        if topic not in context.agent_context.findings:
            return f"No findings found for topic '{topic}'."
        
        findings = context.agent_context.findings[topic]
        result = f"Findings for topic '{topic}':\n"
        for i, finding in enumerate(findings, 1):
            result += f"{i}. {finding}\n"
        return result
    
    # Return all findings
    result = "All findings:\n"
    for topic, findings in context.agent_context.findings.items():
        result += f"\nTopic: {topic}\n"
        for i, finding in enumerate(findings, 1):
            result += f"{i}. {finding}\n"
    return result 