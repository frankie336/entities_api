# src/api/entities_api/__main__.py
import typer

from entities_api.cli.bootstrap_admin import bootstrap_admin

root = typer.Typer(
    name="entities-api",
    help="Entities API management commands.",
    add_completion=False,
)

root.command(name="bootstrap-admin")(bootstrap_admin)

if __name__ == "__main__":
    root()
