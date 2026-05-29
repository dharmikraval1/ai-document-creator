import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Create a mock for core.graph to avoid importing heavy LLM libraries locally
mock_graph = MagicMock()
mock_graph.app = MagicMock()
sys.modules["core.graph"] = mock_graph

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.repo_loader import RepoLoader

class TestGitIntegration(unittest.TestCase):

    def test_url_authentication_rewriting(self):
        """Verify that RepoLoader properly rewrites https repository URLs with the token."""
        # Test basic HTTPS URL
        loader = RepoLoader("https://github.com/user/repo", github_token="my-secret-token")
        self.assertEqual(loader.repo_url, "https://my-secret-token@github.com/user/repo")
        
        # Test HTTPS URL with .git ending
        loader2 = RepoLoader("https://github.com/user/repo.git", github_token="my-secret-token")
        self.assertEqual(loader2.repo_url, "https://my-secret-token@github.com/user/repo.git")

        # Test URL already containing token/auth (should not double-inject)
        loader3 = RepoLoader("https://other-token@github.com/user/repo.git", github_token="new-token")
        self.assertEqual(loader3.repo_url, "https://other-token@github.com/user/repo.git")

        # Test with no token
        loader4 = RepoLoader("https://github.com/user/repo.git", github_token=None)
        self.assertEqual(loader4.repo_url, "https://github.com/user/repo.git")

    @patch("mcp_server_impl.RepoLoader")
    @patch("mcp_server_impl.DocumentationWriter")
    @patch("git.Repo")
    def test_document_repo_with_push_enabled(self, MockRepo, MockDocWriter, MockRepoLoader):
        """Verify the full document_repo tool behavior when push_to_repo is enabled."""
        # Setup AsyncMock for ainvoke before importing tool
        mock_ainvoke = unittest.mock.AsyncMock()
        mock_ainvoke.return_value = {
            "documents": {"file1.py": "# Doc for file1"},
            "index_content": "# Generated README content"
        }
        
        # Inject the mock
        import mcp_server_impl
        mcp_server_impl.workflow_app.ainvoke = mock_ainvoke
        
        from mcp_server_impl import document_repo
        
        # 1. Setup Mocks
        mock_loader_instance = MockRepoLoader.return_value
        mock_loader_instance.clone_repo.return_value = "/fake/repo/path"
        
        # Mock FileTraverser inside the tool execution
        with patch("mcp_server_impl.FileTraverser") as MockFileTraverser:
            mock_traverser_instance = MockFileTraverser.return_value
            mock_traverser_instance.traverse.return_value = ["file1.py"]
            
            # Mock Repo instance operations
            mock_repo_instance = MockRepo.return_value
            mock_repo_instance.is_dirty.return_value = True
            
            # Mock open() for writing the readme inside the fake repo
            mock_open = unittest.mock.mock_open()
            with patch("builtins.open", mock_open):
                # 2. Run the tool function
                result = asyncio.run(document_repo(
                    repo_url="https://github.com/user/repo",
                    output_dir="docs",
                    push_to_repo=True,
                    github_token="fake-token",
                    commit_message="custom docs commit"
                ))
                
                # 3. Assertions
                # Check RepoLoader was initialized with token
                MockRepoLoader.assert_called_once_with("https://github.com/user/repo", github_token="fake-token")
                
                # Check that git repository actions were invoked
                MockRepo.assert_called_once_with("/fake/repo/path")
                
                # Check that config was written for commit author info
                mock_repo_instance.config_writer.assert_called_once()
                
                # Check git add, commit, and push were called
                mock_repo_instance.git.add.assert_called_once_with(A=True)
                mock_repo_instance.index.commit.assert_called_once_with("custom docs commit")
                mock_repo_instance.remotes.origin.push.assert_called_once()
                
                # Check that README content is included in the output report
                self.assertIn("# Generated README content", result)
                self.assertIn("Successfully committed and pushed to GitHub", result)
                self.assertIn("GitHub Push Status", result)

if __name__ == "__main__":
    unittest.main()
