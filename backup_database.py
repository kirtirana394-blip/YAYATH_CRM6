from datetime import datetime, timedelta
from pathlib import Path
import sqlite3


PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "instance" / "99acres_crm.db"
BACKUP_DIR = Path.home() / "Documents" / "99Acres CRM Backups"
RETENTION_DAYS = 30


def backup_database():
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DATABASE_PATH}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = BACKUP_DIR / f"99acres_crm_{timestamp}.db"

    with sqlite3.connect(DATABASE_PATH) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    for old_backup in BACKUP_DIR.glob("99acres_crm_*.db"):
        if datetime.fromtimestamp(old_backup.stat().st_mtime) < cutoff:
            old_backup.unlink()

    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    backup_database()
