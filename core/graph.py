import os
import re
from typing import List, Dict, TypedDict, Annotated
from concurrent.futures import ThreadPoolExecutor
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Define Agent State
class AgentState(TypedDict):
    repo_path: str
    files: List[str]
    documents: Dict[str, str]  # Map file path to generated documentation
    index_content: str

# LLM Setup
# Prioritize AWS Bedrock if AWS credentials are set, then Azure OpenAI, then standard OpenAI
if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
    from langchain_aws import ChatBedrock
    llm = ChatBedrock(
        model_id=os.getenv("AWS_BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        temperature=0
    )
elif os.getenv("AZURE_OPENAI_API_KEY"):
    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
        openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        temperature=0
    )
else:
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Prompts
doc_prompt = ChatPromptTemplate.from_template(
    """
    You are an expert technical writer. Generate comprehensive documentation for the following code file:
    
    File Path: {file_path}
    
    Code Content:
    {code_content}
    
    Output Format:
    Markdown
    
    Include:
    ### Summary
    A concise 1-2 sentence high-level summary of the file's purpose and functionality.
    
    ### Overview
    A detailed overview of the file's role and importance in the system.
    
    ### Key Classes and Functions
    Detailed breakdown of main classes, functions, and key methods, including parameter types, return values, and behavior.
    
    ### Usage Examples
    Code snippets or explanations of how to import and use this component (if applicable).
    """
)

index_prompt = ChatPromptTemplate.from_template(
    """
    You are an expert technical writer. Generate a premium, comprehensive main README.md (Index) for the following repository.
    
    Repository Structure (Files):
    {file_list}
    
    Generated Documentation Summaries:
    {doc_summaries}
    
    Output Format:
    Markdown
    
    Please write a beautiful, professional, and detailed README.md containing:
    1. **Project Title**: A catchy and descriptive project name.
    2. **Project Overview**: An in-depth description explaining the purpose of the repository.
    3. **Architecture & Key Components**: Structure of the directory and explanation of key components based on the file summaries.
    4. **Installation**: How to set up dependencies and environment.
    5. **Usage**: How to run/use the project.
    6. **Running Tests**: How to run the automated tests.
    """
)

# Nodes
def analyze_repo(state: AgentState):
    """Placeholder for any initial analysis. Currently just passes through."""
    return {"files": state["files"]}

def generate_docs(state: AgentState):
    """Generates documentation for each file in parallel."""
    repo_path = state["repo_path"]
    files = state["files"]
    documents = {}
    
    def process_file(file_path):
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            chain = doc_prompt | llm | StrOutputParser()
            doc = chain.invoke({"file_path": file_path, "code_content": content})
            return file_path, doc
        except Exception as e:
            return file_path, f"Error generating documentation: {e}"

    # Parallel LLM calls
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_file, files)
        
    for file_path, doc in results:
        documents[file_path] = doc
            
    return {"documents": documents}

def generate_index(state: AgentState):
    """Generates the main index/README."""
    files = state["files"]
    documents = state["documents"]
    
    def extract_summary(doc_content: str) -> str:
        # Extract content under ### Summary up to the next header or empty lines
        match = re.search(r"### Summary\s*([\s\S]*?)(?=(?:##|###)|$)", doc_content, re.IGNORECASE)
        if match:
            summary = match.group(1).strip()
            if summary:
                return summary
        # Clean markdown headings and grab the beginning of the file as fallback
        cleaned = re.sub(r"#+\s+.*", "", doc_content).strip()
        cleaned = "\n".join([line for line in cleaned.splitlines() if line.strip()])
        return cleaned[:200] + "..." if len(cleaned) > 200 else cleaned

    # Create high-quality summaries for the index prompt
    summaries_list = []
    for file_path, doc in documents.items():
        summary = extract_summary(doc)
        summaries_list.append(f"- **{file_path}**: {summary}")
        
    doc_summaries = "\n".join(summaries_list)
    
    chain = index_prompt | llm | StrOutputParser()
    index_content = chain.invoke({"file_list": "\n".join(files), "doc_summaries": doc_summaries})
    
    return {"index_content": index_content}

# Graph Construction
workflow = StateGraph(AgentState)

workflow.add_node("analyze_repo", analyze_repo)
workflow.add_node("generate_docs", generate_docs)
workflow.add_node("generate_index", generate_index)

workflow.set_entry_point("analyze_repo")
workflow.add_edge("analyze_repo", "generate_docs")
workflow.add_edge("generate_docs", "generate_index")
workflow.add_edge("generate_index", END)

app = workflow.compile()
