import os
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

@tool
def calculator_tool(expression: str) -> str:
    """Useful for when you need to answer questions about math."""
    return str(eval(expression, {"__builtins__": {}}, {}))

llm = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="dummy",
    model="nvidia/nemotron-3-nano-30b-a3b:free",
)

agent = create_agent(model=llm, tools=[calculator_tool])
print(agent)
