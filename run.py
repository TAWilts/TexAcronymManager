"""Run the app directly from a cloned/downloaded source folder."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tacroman.web_app import main


if __name__ == "__main__":
    main()
