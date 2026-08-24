from agents import function_tool

@function_tool
def search_information(query: str) -> str:
    """
    Search for information about a given query.
    
    Args:
        query: The search query string
        
    Returns:
        A string containing the search results
    """
    # In a real implementation, this would call a search API or database
    # For this example, we'll return a mock response
    return f"Here are the search results for '{query}':\n" \
           f"- Result 1: Information about {query}\n" \
           f"- Result 2: More details about {query}\n" \
           f"- Result 3: Additional context for {query}" 