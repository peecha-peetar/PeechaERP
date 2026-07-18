"""تنظیمات برنامه؛ از متغیرهای محیطی (.env) خوانده می‌شود."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


def load_database_config() -> DatabaseConfig:
    return DatabaseConfig(
        host=os.environ.get("PEECHA_DB_HOST", "localhost"),
        port=int(os.environ.get("PEECHA_DB_PORT", "5432")),
        name=os.environ.get("PEECHA_DB_NAME", "peecha"),
        user=os.environ.get("PEECHA_DB_USER", "peecha"),
        password=os.environ.get("PEECHA_DB_PASSWORD", ""),
    )
