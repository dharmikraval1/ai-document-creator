# AI-Driven Documentation Generator for GitHub Repositories

## Project Overview

Welcome to the AI-Driven Documentation Generator for GitHub Repositories! This project aims to automate the generation of comprehensive documentation for any GitHub repository using advanced AI techniques. By leveraging the power of AI, this tool clones a specified repository, traverses its files, processes them, and generates detailed documentation, making it easier for developers to understand and contribute to the project.

## Architecture & Key Components

The repository is structured to facilitate easy maintenance and scalability. Below is a detailed breakdown of the directory structure and the purpose of each component:

### Directory Structure

```
.
├── Dockerfile
├── scratch_test_push.py
├── verification_script.py
├── requirements.txt
├── main.py
├── mcp_server_impl.py
├── .gitignore
├──.env.example
└── core
    ├── file_traverser.py
    ├── repo_loader.py
    ├── graph.py
    └── doc_writer.py
```

### Key Components

- **Dockerfile**: Builds a Docker image for the Python application, setting up the environment and installing dependencies for running the MCP server.
- **scratch_test_push.py**: Contains unit tests for the `RepoLoader` class and the `document_repo` function, ensuring the reliability of URL authentication rewriting and documentation generation.
- **verification_script.py**: Verifies the documentation generation process by creating a temporary repository, traversing files, simulating graph execution, writing output, and verifying generated documentation files.
- **requirements.txt**: Lists all Python packages required for the project, ensuring all dependencies are clearly defined and easily installable.
- **main.py**: The entry point for the AI-driven document creator. It clones a specified GitHub repository, traverses its files, processes them using a LangGraph application, and generates documentation.
- **mcp_server_impl.py**: Implements an AI-driven server for generating documentation for GitHub repositories using the `FastMCP` framework.
- **.gitignore**: Specifies intentionally untracked files that Git should ignore, maintaining a clean and manageable repository.
- **.env.example**: Provides a template for environment variables required to configure and run applications that interact with Azure OpenAI and AWS Bedrock services.
- **core/file_traverser.py**: Contains the `FileTraverser` class, which traverses a directory and yields file paths, filtering out ignored and binary files, and respecting a maximum file size limit.
- **core/repo_loader.py**: Provides the `RepoLoader` class designed to handle the cloning of Git repositories, including authentication and cleanup of temporary directories.
- **core/graph.py**: Implements the documentation generation graph, processing repository files and generating documentation nodes.
- **core/doc_writer.py**: Contains the `DocumentationWriter` class, responsible for writing generated documentation to files in a specified output directory in Markdown format.

## Installation

To set up the project and its dependencies, follow these steps:

1. **Clone the Repository**:
    ```bash
    git clone https://github.com/your-repo/ai-documentation-generator.git
    cd ai-documentation-generator
    ```

2. **Create a Virtual Environment** (optional but recommended):
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4. **Configure Environment Variables**:
    Copy `.env.example` to `.env` and fill in the required values for Azure OpenAI and AWS Bedrock services.

## Usage

To generate documentation for a GitHub repository, run the following command:

```bash
python main.py --repo-url https://github.com/username/repo
```

This will clone the repository, traverse its files, process them using the AI-driven graph, and generate documentation in the specified output directory.

## Running Tests

To ensure the project functions correctly, run the automated tests:

1. **Run Unit Tests**:
    ```bash
    python -m unittest discover
    ```

2. **Run Verification Script**:
    ```bash
    python verification_script.py
    ```

These tests will verify the functionality of the documentation generation process and ensure that all components work seamlessly together.

---

Thank you for using the AI-Driven Documentation Generator for GitHub Repositories. We hope this tool simplifies the process of generating comprehensive documentation for your projects!
