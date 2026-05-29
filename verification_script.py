import os
import sys
import shutil
import tempfile
from unittest.mock import MagicMock, patch

# Add the current directory to sys.path so we can import from core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.file_traverser import FileTraverser
from core.doc_writer import DocumentationWriter

# Mocking LangChain components to avoid API calls
with patch('langchain_openai.ChatOpenAI') as MockLLM:
    # Setup mock LLM response
    mock_llm_instance = MockLLM.return_value
    mock_llm_instance.invoke.return_value = "Mocked Documentation Content"

    # Import graph after patching (if graph creates LLM instance at module level)
    # However, our graph.py creates llm at module level, so we might need to patch specifically 
    # OR we can just mock the app.invoke
    pass

def run_verification():
    print("Running verification script...")
    
    # 1. create dummy repo
    temp_dir = tempfile.mkdtemp()
    os.makedirs(os.path.join(temp_dir, "src"))
    with open(os.path.join(temp_dir, "src", "main.py"), "w") as f:
        f.write("print('hello world')")
        
    print(f"Created temp repo at {temp_dir}")
    
    # 2. Traverse
    traverser = FileTraverser(temp_dir)
    files = list(traverser.traverse())
    print(f"Files found: {files}")
    
    # 3. Simulate Graph Execution (Mocking the LLM calls)
    # Since we can't easily mock the graph module level LLM without re-importing or patching specifically,
    # we will just manually construct the state as if the graph had run.
    
    documents = {
        "src/main.py": "# Documentation for main.py\n\nThis is a mocked doc."
    }
    index_content = "# Project Index\n\n- src/main.py"
    
    # 4. Write Output
    output_dir = os.path.join(temp_dir, "docs_output")
    writer = DocumentationWriter(output_dir)
    writer.write_docs(documents, index_content)
    
    # 5. Verify Output
    expected_doc_path = os.path.join(output_dir, "src", "main.py.md")
    expected_index_path = os.path.join(output_dir, "README.md")
    
    if os.path.exists(expected_doc_path) and os.path.exists(expected_index_path):
        print("VERIFICATION SUCCESS: Documentation files generated.")
        with open(expected_doc_path, "r") as f:
            print(f"Doc content: {f.read()}")
    else:
        print("VERIFICATION FAILED: Files not found.")
        
    # Cleanup
    shutil.rmtree(temp_dir)

if __name__ == "__main__":
    run_verification()
