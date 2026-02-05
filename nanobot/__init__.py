"""
nanobot - A lightweight AI agent framework
"""

import warnings
import logging

# Configure logging to suppress Pydantic warnings before any imports
logging.getLogger("pydantic").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning)

__version__ = "0.1.0"
__logo__ = "🐈"
