import os
from pathlib import Path
from threading import Timer

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = ROOT / "e2e-opspilot.db"


def main() -> None:
    DATABASE_PATH.unlink(missing_ok=True)
    os.environ["OPSPILOT_DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{DATABASE_PATH.as_posix()}"
    )
    os.environ["OPSPILOT_APPROVAL_TTL_SECONDS"] = "5"
    os.chdir(ROOT)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")

    import uvicorn

    from apps.api.main import app

    @app.post("/__e2e_shutdown", include_in_schema=False)
    async def shutdown_e2e_server() -> dict[str, str]:
        Timer(0.2, os._exit, args=(0,)).start()
        return {"status": "stopping"}

    uvicorn.run(app, host="127.0.0.1", port=8010)


if __name__ == "__main__":
    main()
