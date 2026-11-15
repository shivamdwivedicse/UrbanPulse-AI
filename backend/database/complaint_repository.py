"""SQLite persistence for citizen complaints."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from backend.schemas.complaint import ComplaintPriority, ComplaintStatus, ComplaintCategory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent / "complaints.sqlite3"


class ComplaintRepository:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialization_lock = threading.Lock()
        self.initialize()

    def initialize(self) -> None:
        with self._initialization_lock:
            with sqlite3.connect(self.database_path, timeout=5) as connection:
                connection.execute("PRAGMA busy_timeout = 5000")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS complaints (
                        complaint_id TEXT PRIMARY KEY,
                        citizen_name TEXT NOT NULL,
                        contact TEXT NOT NULL,
                        category TEXT NOT NULL CHECK (
                            category IN (
                                'Garbage Overflow',
                                'Uncollected Waste',
                                'Illegal Dumping',
                                'Damaged Dustbin',
                                'Other'
                            )
                        ),
                        description TEXT NOT NULL,
                        location TEXT NOT NULL,
                        latitude REAL,
                        longitude REAL,
                        image_path TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN (
                                'Submitted',
                                'Under Review',
                                'In Progress',
                                'Resolved',
                                'Rejected'
                            )
                        ),
                        priority TEXT NOT NULL CHECK (
                            priority IN ('Low', 'Medium', 'High')
                        ),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CHECK (
                            (latitude IS NULL AND longitude IS NULL)
                            OR (latitude IS NOT NULL AND longitude IS NOT NULL)
                        )
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_complaints_created_at "
                    "ON complaints(created_at DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_complaints_status "
                    "ON complaints(status)"
                )
                connection.commit()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, complaint: dict[str, object]) -> dict[str, object]:
        fields = (
            "complaint_id",
            "citizen_name",
            "contact",
            "category",
            "description",
            "location",
            "latitude",
            "longitude",
            "image_path",
            "status",
            "priority",
            "created_at",
            "updated_at",
        )
        values = tuple(complaint[field] for field in fields)
        placeholders = ", ".join("?" for _ in fields)
        with self._connection() as connection:
            connection.execute(
                f"INSERT INTO complaints ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?",
                (complaint["complaint_id"],),
            ).fetchone()
        return dict(row)

    def list(
        self,
        *,
        complaint_status: Optional[ComplaintStatus] = None,
        category: Optional[ComplaintCategory] = None,
        priority: Optional[ComplaintPriority] = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[str] = []
        if complaint_status is not None:
            clauses.append("status = ?")
            values.append(complaint_status.value)
        if category is not None:
            clauses.append("category = ?")
            values.append(category.value)
        if priority is not None:
            clauses.append("priority = ?")
            values.append(priority.value)
        where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM complaints{where_clause} "
                "ORDER BY created_at DESC, complaint_id DESC",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, complaint_id: str) -> Optional[dict[str, object]]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_status(
        self, complaint_id: str, complaint_status: ComplaintStatus, updated_at: str
    ) -> Optional[dict[str, object]]:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE complaints SET status = ?, updated_at = ? "
                "WHERE complaint_id = ?",
                (complaint_status.value, updated_at, complaint_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()
        return dict(row)
