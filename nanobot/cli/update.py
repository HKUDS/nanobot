"""Command-line updates for release and source installations."""

import typer


def update(
    dev: bool = typer.Option(False, "--dev", "--update-dev", help="Install or update an editable source checkout and build its WebUI."),
    check: bool = typer.Option(False, "--check", help="Check the latest stable release without installing."),
    allow_downgrade: bool = typer.Option(False, "--allow-downgrade", help="Allow an intentional return to an older stable release. Back up data first."),
) -> None:
    """Update nanobot in the current Python environment."""
    from nanobot import __version__
    from nanobot.update import latest_release, update_installation

    if check and dev:
        raise typer.BadParameter("--check checks PyPI releases; use it without --dev.")
    try:
        if check:
            typer.echo(f"Installed: {__version__}\nLatest release: {latest_release()}")
            return
        result = update_installation(dev=dev, allow_downgrade=allow_downgrade, output=typer.echo)
    except (RuntimeError, OSError, ValueError) as exc:
        typer.echo(f"Update failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if result["requires_restart"]:
        typer.echo(f"Installed nanobot {result['version']}. Restart nanobot to use it; the running process has not been verified.")
    else:
        typer.echo(f"nanobot {result['version']} is already installed. No files changed.")
