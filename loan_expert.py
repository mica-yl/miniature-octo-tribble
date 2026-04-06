import os
import ast
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_classic.tools import Tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from dotenv import load_dotenv

# This looks for a .env file and loads it into the environment
load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")

# ==========================================
# 1. Define the Calculator Tool
# Replicates "CalculatorComponent-3bKa9"
# ==========================================
def calculate_expression(expression: str) -> str:
    """Evaluates a mathematical expression."""
    try:
        # A simple mathematical evaluator 
        # (In production, consider using numexpr or python's ast for safer evaluation)
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{float(result):.6f}".rstrip("0").rstrip(".")
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error calculating expression: {e}"

calculator_tool = Tool(
    name="Calculator",
    func=calculate_expression,
    description="Useful for when you need to answer questions about math. Input should be a strictly mathematical expression (e.g., '15000 * 12')."
)

tools = [calculator_tool]

# ==========================================
# 2. Define Prompts and Templates
# Replicates Prompt-6CxQO, Prompt-q7UT2, & Prompt Template-VmE7z
# ==========================================

# Base System Instructions
sys_instructions = """Role: You are a consultant (sub-agent) for data from a bank. answers only from the data provided.

Core Instructions:
answer as concisely as possible
make sure to provide correct numbers and use calculator tool to calculate.
"""

# Bank / Loan Data Context 
# (This represents the data injected from your prompt template)
def get_bank_data() -> str:
    try:
        with open("loan_data.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Bank data file not found."

# Combine into a single Agent Prompt Template
agent_prompt = ChatPromptTemplate.from_messages([
    ("system", f"{sys_instructions}\n\nBank Data:\n{{bank_data}}"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# ==========================================
# 3. Initialize Model 
# Replicates "OpenRouterComponent-ZsJKc"
# ==========================================
# OpenRouter is API-compatible with OpenAI, so we use ChatOpenAI with the OpenRouter Base URL.
llm = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    # api_key=os.environ.get("OPENROUTER_API_KEY", "your_openrouter_api_key_here"),
    api_key=API_KEY,
    model="nvidia/nemotron-3-nano-30b-a3b:free", # Replace with your chosen OpenRouter model
    temperature=0.1
)

# ==========================================
# 4. Create and Run the Agent
# Replicates "Agent-J2k2O" to "ChatOutput-mkOP3"
# ==========================================

# Bind tools and prompt to the agent
agent = create_tool_calling_agent(llm, tools, agent_prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

def ask_loan_expert(user_message: str) -> str:
    """Answers a single question using the loan data consultant agent."""
    bank_data_content = get_bank_data()
    response = agent_executor.invoke({
        "input": user_message,
        "bank_data": bank_data_content
    })
    return response["output"]

# --- Example Usage ---
if __name__ == "__main__":
    print("Agent Initialized. Type 'exit' to stop.\n")
    while True:
        user_input = input("User: ")
        if user_input.lower() in ['exit', 'quit']:
            break
        
        reply = ask_loan_expert(user_input)
        print(f"\nAI: {reply}\n")