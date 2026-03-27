"""Nanobot Web UI - Flask-based web interface."""

import asyncio
import json
import os
import threading
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response, render_template, current_app
from flask_cors import CORS

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config


def ensure_config_exists(config_path: Path) -> bool:
    """Ensure config file exists, create default if missing."""
    if config_path.exists():
        return True
    
    try:
        # Create parent directories
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create default config
        config = Config()
        save_config(config, config_path)
        
        return True
    except Exception as e:
        print(f"Warning: Could not create config file: {e}")
        return False


def ensure_workspace_exists(workspace_path: Path) -> bool:
    """Ensure workspace directory exists."""
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"Warning: Could not create workspace directory: {e}")
        return False


def create_app(config_path: Path | None = None, workspace_path: Path | None = None):
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent.parent / "templates" / "web"),
        static_folder=str(Path(__file__).parent.parent / "static"),
    )

    # Enable CORS for API endpoints
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Configuration
    app.config["SECRET_KEY"] = os.environ.get("NANOBOT_WEB_SECRET", os.urandom(24).hex())
    app.config["AUTH_TOKEN"] = os.environ.get("NANOBOT_WEB_AUTH_TOKEN", "")

    # Store config paths
    config_path = config_path or get_config_path()
    app.config["CONFIG_PATH"] = config_path
    app.config["WORKSPACE_PATH"] = workspace_path
    
    # Ensure config and workspace exist
    config_exists = ensure_config_exists(config_path)
    if workspace_path:
        ensure_workspace_exists(workspace_path)
    
    # Log config status
    if config_exists:
        print(f"✓ Config loaded from: {config_path}")
    else:
        print(f"⚠ Config file missing and could not be created: {config_path}")

    # Register routes
    register_routes(app)
    register_api_routes(app)
    register_auth_routes(app)

    return app


def require_auth(f):
    """Decorator to require authentication for API routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_token = request.headers.get("X-Auth-Token") or request.args.get("token")
        expected_token = current_app.config.get("AUTH_TOKEN", "")

        # If no token is configured, allow access (for local dev)
        if not expected_token:
            return f(*args, **kwargs)

        if not auth_token or auth_token != expected_token:
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)
    return decorated_function


def register_routes(app):
    """Register main routes."""

    @app.route("/")
    def index():
        """Serve the main dashboard."""
        return render_template("index.html", active_page="dashboard")

    @app.route("/config")
    def config_page():
        """Serve the configuration page."""
        return render_template("config.html", active_page="config")

    @app.route("/chat")
    def chat_page():
        """Serve the chat page."""
        return render_template("chat.html", active_page="chat")

    @app.route("/status")
    def status_page():
        """Serve the status page."""
        return render_template("status.html", active_page="status")

    @app.route("/channels")
    def channels_page():
        """Serve the channels page."""
        return render_template("channels.html", active_page="channels")

    @app.route("/health")
    def health():
        """Health check endpoint for Koyeb."""
        return jsonify({
            "status": "healthy",
            "version": "0.1.4.post5"
        }), 200


def register_api_routes(app):
    """Register API routes."""
    
    @app.route("/api/config", methods=["GET"])
    @require_auth
    def get_config():
        """Get current configuration."""
        try:
            config = load_config(app.config["CONFIG_PATH"])
            config_dict = config.model_dump(mode="json", by_alias=True)
            return jsonify(config_dict)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/config", methods=["POST"])
    @require_auth
    def save_config_route():
        """Save configuration."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400
            
            # Load existing config to preserve any fields not in the request
            config = load_config(app.config["CONFIG_PATH"])
            
            # Update config with provided data
            # This is a simplified update - in production, you'd want more robust validation
            update_config_from_dict(config, data)
            
            # Save updated config
            save_config(config, app.config["CONFIG_PATH"])
            
            return jsonify({"success": True, "message": "Configuration saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/status", methods=["GET"])
    @require_auth
    def get_status():
        """Get system status."""
        try:
            config_path = app.config["CONFIG_PATH"]
            config = load_config(config_path)

            status = {
                "config_exists": config_path.exists(),
                "workspace_exists": config.workspace_path.exists() if config.workspace_path else False,
                "model": config.agents.defaults.model if config.agents.defaults else "Not configured",
                "providers": {},
                "channels": {},
                "gateway": {
                    "port": config.gateway.port if config.gateway else 18790,
                    "heartbeat_enabled": config.gateway.heartbeat.enabled if config.gateway and config.gateway.heartbeat else True,
                    "heartbeat_interval": config.gateway.heartbeat.interval_s if config.gateway and config.gateway.heartbeat else 1800,
                },
                "tools": {
                    "web_search_provider": config.tools.web.search.provider if config.tools and config.tools.web and config.tools.web.search else "brave",
                    "exec_enabled": config.tools.exec.enable if config.tools and config.tools.exec else True,
                    "restrict_to_workspace": config.tools.restrict_to_workspace if config.tools else False,
                }
            }

            # Check provider status
            try:
                from nanobot.providers.registry import PROVIDERS
                for spec in PROVIDERS:
                    p = getattr(config.providers, spec.name, None)
                    if p is None:
                        continue
                    if spec.is_oauth:
                        status["providers"][spec.name] = {"status": "oauth", "configured": True}
                    elif spec.is_local:
                        status["providers"][spec.name] = {
                            "status": "local",
                            "configured": bool(p.api_base),
                            "api_base": p.api_base
                        }
                    else:
                        status["providers"][spec.name] = {
                            "status": "api_key",
                            "configured": bool(p.api_key)
                        }
            except Exception as e:
                print(f"Warning: Could not load providers: {e}")
                status["providers"] = {"error": "Could not load providers"}

            # Check channel status
            try:
                from nanobot.channels.registry import discover_all
                all_channels = discover_all()
                for name, cls in all_channels.items():
                    section = getattr(config.channels, name, None)
                    if section is None:
                        enabled = False
                    elif isinstance(section, dict):
                        enabled = section.get("enabled", False)
                    else:
                        enabled = getattr(section, "enabled", False)
                    status["channels"][name] = {
                        "display_name": cls.display_name,
                        "enabled": enabled
                    }
            except Exception as e:
                print(f"Warning: Could not load channels: {e}")
                status["channels"] = {"error": "Could not load channels"}

            return jsonify(status)
        except Exception as e:
            print(f"Error in /api/status: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/providers", methods=["GET"])
    @require_auth
    def get_providers():
        """Get available providers and their models."""
        try:
            from nanobot.providers.registry import PROVIDERS
            
            providers = []
            for spec in PROVIDERS:
                providers.append({
                    "name": spec.name,
                    "display_name": spec.label,
                    "is_oauth": spec.is_oauth,
                    "is_local": spec.is_local,
                    "is_gateway": spec.is_gateway,
                    "keywords": spec.keywords,
                    "default_api_base": spec.default_api_base,
                })
            
            return jsonify({"providers": providers})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/models/suggestions", methods=["GET"])
    @require_auth
    def get_model_suggestions():
        """Get model suggestions."""
        try:
            from nanobot.cli.models import get_model_suggestions
            
            provider = request.args.get("provider", "")
            suggestions = get_model_suggestions(provider)
            
            return jsonify({"models": suggestions})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/channels", methods=["GET"])
    @require_auth
    def get_channels():
        """Get available channels."""
        try:
            from nanobot.channels.registry import discover_all
            
            config = load_config(app.config["CONFIG_PATH"])
            all_channels = discover_all()
            
            channels = []
            for name, cls in all_channels.items():
                section = getattr(config.channels, name, None) or {}
                if isinstance(section, dict):
                    enabled = section.get("enabled", False)
                    config_data = section
                else:
                    enabled = getattr(section, "enabled", False)
                    config_data = {}
                
                channels.append({
                    "name": name,
                    "display_name": cls.display_name,
                    "enabled": enabled,
                    "config": config_data,
                    "has_login": hasattr(cls, "login"),
                })
            
            return jsonify({"channels": channels})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/chat", methods=["POST"])
    @require_auth
    def chat():
        """Send a message to the agent."""
        try:
            import asyncio

            data = request.get_json()
            message = data.get("message", "")
            session_id = data.get("session_id", "web:default")

            if not message:
                return jsonify({"error": "Message is required"}), 400

            # Run the agent in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                response = loop.run_until_complete(
                    run_agent_message(message, session_id, current_app.config["CONFIG_PATH"])
                )
                return jsonify({
                    "success": True,
                    "response": response.content if response else "",
                    "metadata": response.metadata if response else {}
                })
            finally:
                loop.close()

        except Exception as e:
            print(f"Error in /api/chat: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/chat/stream", methods=["POST"])
    @require_auth
    def chat_stream():
        """Stream a message to the agent using SSE (simplified for now)."""
        # For now, use the same implementation as /api/chat
        # Streaming can be implemented properly later
        import asyncio

        data = request.get_json()
        message = data.get("message", "")
        session_id = data.get("session_id", "web:default")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        # Run the agent in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            response = loop.run_until_complete(
                run_agent_message(message, session_id, current_app.config["CONFIG_PATH"])
            )
            
            # Return as SSE format for compatibility
            return Response(
                f"data: {json.dumps({'response': response.content if response else '', 'metadata': response.metadata if response else {}})}\n\ndata: [DONE]\n\n",
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                }
            )
        except Exception as e:
            print(f"Error in /api/chat/stream: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
        finally:
            loop.close()


def register_auth_routes(app):
    """Register authentication routes."""
    
    @app.route("/api/auth/check", methods=["GET"])
    def check_auth():
        """Check if authentication is required."""
        auth_token = app.config.get("AUTH_TOKEN", "")
        return jsonify({
            "auth_required": bool(auth_token),
            "authenticated": not bool(auth_token)  # If no token, consider authenticated
        })
    
    @app.route("/api/auth/verify", methods=["POST"])
    def verify_auth():
        """Verify authentication token."""
        data = request.get_json()
        token = data.get("token", "")
        expected_token = app.config.get("AUTH_TOKEN", "")
        
        if not expected_token:
            return jsonify({"authenticated": True})
        
        if token == expected_token:
            return jsonify({"authenticated": True})
        else:
            return jsonify({"authenticated": False}), 401


async def run_agent_message(message: str, session_id: str, config_path: Path):
    """Run agent message processing in async context."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.cli.commands import _make_provider
    
    config = load_config(config_path)
    bus = MessageBus()
    provider = _make_provider(config)
    
    # Create cron service
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent loop
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )
    
    try:
        response = await agent_loop.process_direct(
            message,
            session_id,
            on_progress=lambda c, t=False: None,
        )
        return response
    finally:
        await agent_loop.close_mcp()


def update_config_from_dict(config: Config, data: dict):
    """Update config object from dictionary data."""
    # This is a simplified updater - in production you'd want more robust validation
    for key, value in data.items():
        # Convert camelCase to snake_case
        snake_key = key
        for i, char in enumerate(key):
            if char.isupper() and (i == 0 or not key[i-1].isupper()):
                snake_key = key[:i].lower() + "_" + key[i:]
                break
        
        if hasattr(config, snake_key):
            attr = getattr(config, snake_key)
            if isinstance(attr, dict) and isinstance(value, dict):
                attr.update(value)
            elif isinstance(attr, (list, tuple)) and isinstance(value, (list, tuple)):
                setattr(config, snake_key, value)
            elif hasattr(attr, "model_dump"):
                # It's a Pydantic model, try to update it
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        sub_snake = sub_key
                        for j, c in enumerate(sub_key):
                            if c.isupper() and (j == 0 or not sub_key[j-1].isupper()):
                                sub_snake = sub_key[:j].lower() + "_" + sub_key[j:]
                                break
                        if hasattr(attr, sub_snake):
                            setattr(attr, sub_snake, sub_value)
            else:
                setattr(config, snake_key, value)


# Global app instance for CLI
_app_instance = None


def get_app(config_path: Path | None = None, workspace_path: Path | None = None):
    """Get or create the Flask app instance."""
    global _app_instance
    if _app_instance is None:
        _app_instance = create_app(config_path, workspace_path)
    return _app_instance


def run_server(host: str = "0.0.0.0", port: int = 18790, config_path: Path | None = None, 
             workspace_path: Path | None = None, debug: bool = False):
    """Run the Flask development server."""
    app = get_app(config_path, workspace_path)
    app.run(host=host, port=port, debug=debug, threaded=True)
