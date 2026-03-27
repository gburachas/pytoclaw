"""Skills command — manage skill packages."""

from __future__ import annotations

import asyncio
import importlib.resources
import shutil
from pathlib import Path

import typer
from rich.console import Console

console = Console()
skills_app = typer.Typer(name="skills", help="Manage skill packages")


def _build_loader() -> "SkillsLoader":
    """Build a SkillsLoader with 4-tier paths from config."""
    from pyclaw.config import load_config
    from pyclaw.skills.loader import SkillsLoader

    cfg = load_config()
    workspace = Path(cfg.agents.defaults.workspace).expanduser()

    try:
        builtin_path = Path(str(importlib.resources.files("pyclaw.skills") / "builtins"))
    except (TypeError, FileNotFoundError):
        builtin_path = None

    return SkillsLoader(
        workspace_skills=workspace / "skills",
        project_skills=Path.cwd() / ".agents" / "skills",
        global_skills=Path.home() / ".pyclaw" / "skills",
        builtin_skills=builtin_path,
    )


@skills_app.command("list")
def list_skills() -> None:
    """List all skills from all tiers."""
    loader = _build_loader()
    skills = loader.list_skills()

    if not skills:
        console.print("No skills found.")
        return

    console.print(f"[bold]Skills ({len(skills)}):[/bold]")
    for s in skills:
        console.print(f"  {s.name} [{s.source.value}] — {s.description}")


@skills_app.command("show")
def show_skill(
    name: str = typer.Argument(..., help="Skill name to show"),
) -> None:
    """Display a skill's definition."""
    loader = _build_loader()
    body, found = loader.load_skill(name)
    if not found:
        console.print(f"[red]Skill '{name}' not found.[/red]")
        return
    console.print(body)


@skills_app.command("remove")
def remove_skill(
    name: str = typer.Argument(..., help="Skill name to remove"),
) -> None:
    """Remove an installed skill from workspace."""
    from pyclaw.config import load_config

    cfg = load_config()
    workspace = Path(cfg.agents.defaults.workspace).expanduser()
    skill_dir = workspace / "skills" / name

    if not skill_dir.exists():
        console.print(f"[red]Skill '{name}' not found in workspace.[/red]")
        return

    shutil.rmtree(skill_dir)
    console.print(f"[green]Skill '{name}' removed.[/green]")


@skills_app.command("search")
def search_skills(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
) -> None:
    """Search for skills in configured registries."""
    from pyclaw.config import load_config
    from pyclaw.skills.clawhub import ClawHubConfig, ClawHubRegistry
    from pyclaw.skills.registry import RegistryManager

    cfg = load_config()

    if not cfg.tools.skills.hub_url:
        console.print("[yellow]No skill registries configured. Set tools.skills.hub_url in config.[/yellow]")
        return

    mgr = RegistryManager()
    hub_cfg = ClawHubConfig(
        base_url=cfg.tools.skills.hub_url,
        auth_token=cfg.tools.skills.hub_auth_token,
    )
    mgr.add_registry(ClawHubRegistry(hub_cfg))

    results = asyncio.run(mgr.search_all(query, limit))
    if not results:
        console.print(f"No skills found for '{query}'.")
        return

    console.print(f"[bold]Results for '{query}':[/bold]")
    for r in results:
        console.print(f"  {r.display_name} ({r.slug}) — {r.summary}")
        console.print(f"    Version: {r.version} | Registry: {r.registry_name}")


@skills_app.command("install")
def install_skill(
    source: str = typer.Argument(..., help="GitHub repo (owner/repo) or ClawHub slug"),
    force: bool = typer.Option(False, "--force", "-f", help="Reinstall if exists"),
) -> None:
    """Install a skill from GitHub or ClawHub."""
    from pyclaw.config import load_config

    cfg = load_config()
    workspace = Path(cfg.agents.defaults.workspace).expanduser()

    if "/" in source and not source.startswith("clawhub:"):
        # GitHub repo install
        from pyclaw.skills.github_installer import GitHubInstaller

        installer = GitHubInstaller(str(workspace))
        try:
            result = asyncio.run(installer.install_from_github(source, force=force))
            console.print(f"[green]Installed from GitHub: {result}[/green]")
        except Exception as e:
            console.print(f"[red]Installation failed: {e}[/red]")
    else:
        # ClawHub slug install
        slug = source.removeprefix("clawhub:")
        if not cfg.tools.skills.hub_url:
            console.print("[yellow]No ClawHub registry configured. Set tools.skills.hub_url in config.[/yellow]")
            return

        from pyclaw.skills.clawhub import ClawHubConfig, ClawHubRegistry

        hub_cfg = ClawHubConfig(
            base_url=cfg.tools.skills.hub_url,
            auth_token=cfg.tools.skills.hub_auth_token,
        )
        registry = ClawHubRegistry(hub_cfg)
        target_dir = str(workspace / "skills" / slug)

        try:
            result = asyncio.run(registry.download_and_install(slug, "", target_dir))
            if result.is_malware_blocked:
                console.print(f"[red]Skill '{slug}' is blocked as malware.[/red]")
                return
            console.print(f"[green]Installed '{slug}' v{result.version}[/green]")
        except Exception as e:
            console.print(f"[red]Installation failed: {e}[/red]")
