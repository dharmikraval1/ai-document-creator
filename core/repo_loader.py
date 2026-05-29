import logging
import tempfile
import shutil
import os
# pyrefly: ignore [missing-import]
from git import Repo

logger = logging.getLogger(__name__)

class RepoLoader:
    """Handles cloning of git repositories."""

    def __init__(self, repo_url: str):
        self.repo_url = repo_url
        self.temp_dir = tempfile.mkdtemp()
        self.repo_name = repo_url.split("/")[-1].replace(".git", "")

    def clone_repo(self) -> str:
        """Clones the repository to a temporary directory and returns the path."""
        try:
            logger.info(f"Cloning repository {self.repo_url} to {self.temp_dir}")
            Repo.clone_from(self.repo_url, self.temp_dir)
            return self.temp_dir
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            self.cleanup()  # Clean up if clone fails
            raise

    def cleanup(self):
        """Removes the temporary directory."""
        if os.path.exists(self.temp_dir):
            try:
                def remove_readonly(func, path, excinfo):
                    import stat
                    try:
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    except Exception:
                        pass
                shutil.rmtree(self.temp_dir, onerror=remove_readonly)
                logger.info(f"Cleaned up temporary directory {self.temp_dir}")
            except Exception as e:
                logger.error(f"Failed to clean up temporary directory: {e}")
