"""Command-line updates for release and source installations."""

import asyncio
import subprocess
from typing import Literal

import httpx
import typer


def update(
    dev: bool = typer.Option(False, "--dev", "--update-dev", help="Install or update an editable source checkout and build its WebUI."),
    check: bool = typer.Option(False, "--check", help="Check the latest stable release without installing."),
    allow_downgrade: bool = typer.Option(False, "--allow-downgrade", help="Allow an intentional return to an older stable release. Back up data first."),
    plan: bool = typer.Option(False, "--plan", help="Save an exact release plan without installing or restarting."),
    channel: Literal["stable", "preview"] | None = typer.Option(None, "--channel", help="Release channel to inspect with --plan (default: saved subscription)."),
    job: str | None = typer.Option(None, "--job", help="Read an exact saved job in this installation; does not install."),
    retry_handoff: bool = typer.Option(False, "--retry-handoff", help="With --job, explicitly retry shutdown before package mutation."),
    previous_confirmation: str | None = typer.Option(None, "--previous-confirmation", help="The execution confirmation from the job being retried."),
    confirm_restart: bool = typer.Option(False, "--confirm-restart", help="Confirm the saved plan's shutdown, installation and restart."),
) -> None:
    """Update nanobot in the current Python environment."""
    if job is not None or retry_handoff or previous_confirmation is not None or confirm_restart:
        if job is None or dev or check or allow_downgrade or plan or channel is not None:
            raise typer.BadParameter("Use --job separately from release selection and legacy update flags.")
        if retry_handoff != (previous_confirmation is not None and confirm_restart):
            raise typer.BadParameter("Retry requires --retry-handoff, --previous-confirmation and --confirm-restart together.")
        if not retry_handoff and (previous_confirmation is not None or confirm_restart):
            raise typer.BadParameter("Reading --job cannot authorize a restart.")
        _saved_job(job, previous_confirmation if retry_handoff else None)
        return

    from nanobot import __version__
    from nanobot.update import latest_release, update_installation

    if plan:
        if dev or check or allow_downgrade:
            raise typer.BadParameter("Use --plan with --channel, without execution flags.")
        from nanobot.update_plan import describe_plan, preview_release_update

        try:
            typer.echo(describe_plan(asyncio.run(preview_release_update(channel))))
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError, httpx.HTTPError) as exc:
            typer.echo(f"Could not prepare update plan: {exc}", err=True)
            raise typer.Exit(1) from exc
        return
    if channel is not None:
        raise typer.BadParameter("Channel inspection requires --plan; confirm channel-aware installation in Settings → About.")

    if check and dev:
        raise typer.BadParameter("--check checks PyPI releases; use it without --dev.")
    try:
        if check:
            from nanobot.installation_lock import installation_access

            with installation_access():
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


def _saved_job(plan_id: str, previous_confirmation: str | None) -> None:
    from nanobot.installation_lock import installation_access, installation_state_dir
    from nanobot.update_jobs import read_update_job, retry_handoff
    from nanobot.update_service import UpdateRetryRequest

    try:
        # The console bootstrap also owns this before importing application
        # dependencies. Do not use this route to repair a mutated environment.
        with installation_access():
            job = read_update_job(plan_id)
            if previous_confirmation is not None:
                request = UpdateRetryRequest(id=plan_id, previous_confirmation_id=previous_confirmation,
                                             confirm_restart=True)
                retry_handoff(installation_state_dir() / "jobs" / request.id, request.previous_confirmation_id)
                job = read_update_job(plan_id)
            typer.echo(job.model_dump_json(indent=2))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        typer.echo("Could not read or retry this saved handoff. No automatic repair was started.", err=True)
        raise typer.Exit(1) from exc
