"""Import the main boundaries used by the project."""

from nanobot import __version__
from nanobot.agent.context import ContextBuilder
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import SessionManager


def main() -> None:
    print(f"nanobot={__version__}")
    print("boundaries=Config,MessageBus,ContextBuilder,AgentRunner,ToolRegistry,SessionManager")
    print(f"default_model={Config().agents.defaults.model}")
    print(f"response_type={LLMResponse.__name__}")
    print(f"queue_type={MessageBus.__name__}")
    print(f"context_type={ContextBuilder.__name__}")
    print(f"runner_type={AgentRunner.__name__}")
    print(f"registry_type={ToolRegistry.__name__}")
    print(f"session_type={SessionManager.__name__}")


if __name__ == "__main__":
    main()
