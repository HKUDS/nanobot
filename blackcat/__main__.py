"""
Entry point for running blackcat as a module: python -m blackcat
"""

from blackcat.cli.commands import app

if __name__ == "__main__":
    app()
