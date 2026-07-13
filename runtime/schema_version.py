"""轻量 SQLite Schema migration 管理。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3


MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_files(directory: Path = MIGRATION_DIR) -> list[tuple[int, Path]]:
    """按文件名前缀读取 migration，版本必须唯一递增。"""
    migrations: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        migrations.append((int(path.name.split("_", 1)[0]), path))
    versions = [version for version, _ in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("migration version must be unique")
    return migrations


def _init_migration_table(con: sqlite3.Connection) -> None:
    """初始化 migration 元数据表。"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _pending_versions(database: Path, migrations: list[tuple[int, Path]]) -> list[int]:
    """在不修改数据库的前提下确定待执行版本。"""
    if not database.exists() or database.stat().st_size == 0:
        return [version for version, _ in migrations]
    with sqlite3.connect(database) as con:
        table = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied = set() if table is None else {int(row[0]) for row in con.execute("SELECT version FROM schema_migrations")}
    return [version for version, _ in migrations if version not in applied]


def _backup_before_migration(database: Path, target_version: int) -> Path | None:
    """仅在已有数据库需要升级时创建一次结构迁移备份。"""
    if not database.exists() or database.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = database.with_name(f"{database.name}.pre-v{target_version}-{stamp}.bak")
    # SQLite backup API 能正确处理正在使用中的数据库和 WAL 快照。
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


def apply_schema_migrations(
    database_path: str | Path,
    migration_dir: Path = MIGRATION_DIR,
) -> list[int]:
    """事务化执行尚未应用的 migration，返回本次版本列表。"""
    database = Path(database_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    migrations = _migration_files(migration_dir)
    pending = _pending_versions(database, migrations)
    if pending:
        _backup_before_migration(database, max(pending))
    applied_now: list[int] = []
    with sqlite3.connect(database) as con:
        _init_migration_table(con)
        applied = {int(row[0]) for row in con.execute("SELECT version FROM schema_migrations")}
        for version, path in migrations:
            if version in applied:
                continue
            name = path.name.replace("'", "''")
            script = path.read_text(encoding="utf-8")
            con.executescript(
                f"BEGIN IMMEDIATE;\n{script}\n"
                f"INSERT INTO schema_migrations(version, name) VALUES ({version}, '{name}');\nCOMMIT;"
            )
            applied_now.append(version)
    return applied_now


def current_schema_version(database_path: str | Path) -> int:
    """返回当前 migration 版本；空库返回0。"""
    database = Path(database_path)
    if not database.exists():
        return 0
    with sqlite3.connect(database) as con:
        table = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if table is None:
            return 0
        row = con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0]) if row else 0
