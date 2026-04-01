"""SQLite persistence for TermDash."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    Favorite, Group, GroupFavorite, Layout, LayoutWindow,
    Session, SessionStatus, ShellType, WindowRect,
)

DEFAULT_DB = Path.home() / ".termdash" / "termdash.db"


class Database:
    def __init__(self, path: Path = DEFAULT_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                shell_type TEXT NOT NULL,
                working_dir TEXT DEFAULT '',
                startup_commands TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                layout_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (layout_id) REFERENCES layouts(id)
            );
            CREATE TABLE IF NOT EXISTS group_favorites (
                group_id INTEGER NOT NULL,
                favorite_id INTEGER NOT NULL,
                sort_order INTEGER DEFAULT 0,
                PRIMARY KEY (group_id, favorite_id),
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                FOREIGN KEY (favorite_id) REFERENCES favorites(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS layouts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                monitor_width INTEGER DEFAULT 1920,
                monitor_height INTEGER DEFAULT 1080,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS layout_windows (
                layout_id INTEGER NOT NULL,
                favorite_id INTEGER NOT NULL,
                x INTEGER DEFAULT 0,
                y INTEGER DEFAULT 0,
                width INTEGER DEFAULT 800,
                height INTEGER DEFAULT 600,
                maximized INTEGER DEFAULT 0,
                minimized INTEGER DEFAULT 0,
                PRIMARY KEY (layout_id, favorite_id),
                FOREIGN KEY (layout_id) REFERENCES layouts(id) ON DELETE CASCADE,
                FOREIGN KEY (favorite_id) REFERENCES favorites(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                pid INTEGER NOT NULL,
                window_handle INTEGER,
                favorite_id INTEGER,
                group_id INTEGER,
                label TEXT DEFAULT '',
                shell_type TEXT NOT NULL,
                working_dir TEXT DEFAULT '',
                spawned_at TEXT DEFAULT (datetime('now')),
                status TEXT DEFAULT 'alive'
            );
        """)
        self.conn.commit()

    # --- Favorites ---

    def upsert_favorite(self, fav: Favorite) -> Favorite:
        if fav.id:
            self.conn.execute(
                "UPDATE favorites SET label=?, shell_type=?, working_dir=?, startup_commands=? WHERE id=?",
                (fav.label, fav.shell_type.value, fav.working_dir, fav.commands_json(), fav.id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO favorites (label, shell_type, working_dir, startup_commands) VALUES (?,?,?,?)",
                (fav.label, fav.shell_type.value, fav.working_dir, fav.commands_json()),
            )
            fav.id = cur.lastrowid
        self.conn.commit()
        return fav

    def list_favorites(self) -> list[Favorite]:
        rows = self.conn.execute("SELECT * FROM favorites ORDER BY label").fetchall()
        return [self._row_to_favorite(r) for r in rows]

    def delete_favorite(self, fav_id: int):
        self.conn.execute("DELETE FROM favorites WHERE id=?", (fav_id,))
        self.conn.commit()

    def _row_to_favorite(self, row: sqlite3.Row) -> Favorite:
        return Favorite(
            id=row["id"],
            label=row["label"],
            shell_type=ShellType(row["shell_type"]),
            working_dir=row["working_dir"],
            startup_commands=Favorite.commands_from_json(row["startup_commands"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    # --- Groups ---

    def upsert_group(self, group: Group) -> Group:
        if group.id:
            self.conn.execute(
                "UPDATE groups SET name=?, layout_id=? WHERE id=?",
                (group.name, group.layout_id, group.id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO groups (name, layout_id) VALUES (?,?)",
                (group.name, group.layout_id),
            )
            group.id = cur.lastrowid
        self.conn.commit()
        return group

    def list_groups(self) -> list[Group]:
        rows = self.conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
        return [Group(id=r["id"], name=r["name"], layout_id=r["layout_id"],
                      created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None)
                for r in rows]

    def delete_group(self, group_id: int):
        self.conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        self.conn.commit()

    def set_group_favorites(self, group_id: int, favorite_ids: list[int]):
        self.conn.execute("DELETE FROM group_favorites WHERE group_id=?", (group_id,))
        for i, fid in enumerate(favorite_ids):
            self.conn.execute(
                "INSERT INTO group_favorites (group_id, favorite_id, sort_order) VALUES (?,?,?)",
                (group_id, fid, i),
            )
        self.conn.commit()

    def get_group_favorites(self, group_id: int) -> list[Favorite]:
        rows = self.conn.execute("""
            SELECT f.* FROM favorites f
            JOIN group_favorites gf ON f.id = gf.favorite_id
            WHERE gf.group_id = ?
            ORDER BY gf.sort_order
        """, (group_id,)).fetchall()
        return [self._row_to_favorite(r) for r in rows]

    # --- Layouts ---

    def upsert_layout(self, layout: Layout) -> Layout:
        if layout.id:
            self.conn.execute(
                "UPDATE layouts SET name=?, monitor_width=?, monitor_height=? WHERE id=?",
                (layout.name, layout.monitor_width, layout.monitor_height, layout.id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO layouts (name, monitor_width, monitor_height) VALUES (?,?,?)",
                (layout.name, layout.monitor_width, layout.monitor_height),
            )
            layout.id = cur.lastrowid
        self.conn.commit()
        return layout

    def save_layout_windows(self, layout_id: int, windows: list[LayoutWindow]):
        self.conn.execute("DELETE FROM layout_windows WHERE layout_id=?", (layout_id,))
        for w in windows:
            self.conn.execute(
                "INSERT INTO layout_windows (layout_id, favorite_id, x, y, width, height, maximized, minimized) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (layout_id, w.favorite_id, w.rect.x, w.rect.y,
                 w.rect.width, w.rect.height, int(w.rect.maximized), int(w.rect.minimized)),
            )
        self.conn.commit()

    def get_layout_windows(self, layout_id: int) -> list[LayoutWindow]:
        rows = self.conn.execute(
            "SELECT * FROM layout_windows WHERE layout_id=?", (layout_id,),
        ).fetchall()
        return [
            LayoutWindow(
                layout_id=r["layout_id"],
                favorite_id=r["favorite_id"],
                rect=WindowRect(r["x"], r["y"], r["width"], r["height"],
                                bool(r["maximized"]), bool(r["minimized"])),
            )
            for r in rows
        ]

    # --- Sessions ---

    def save_session(self, session: Session) -> Session:
        if session.id:
            self.conn.execute(
                "UPDATE sessions SET pid=?, window_handle=?, status=?, label=? WHERE id=?",
                (session.pid, session.window_handle, session.status.value, session.label, session.id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO sessions (pid, window_handle, favorite_id, group_id, label, shell_type, working_dir) "
                "VALUES (?,?,?,?,?,?,?)",
                (session.pid, session.window_handle, session.favorite_id, session.group_id,
                 session.label, session.shell_type.value, session.working_dir),
            )
            session.id = cur.lastrowid
        self.conn.commit()
        return session

    def list_sessions(self, status: Optional[SessionStatus] = None) -> list[Session]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM sessions WHERE status=? ORDER BY spawned_at DESC",
                (status.value,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM sessions ORDER BY spawned_at DESC").fetchall()
        return [self._row_to_session(r) for r in rows]

    def clear_dead_sessions(self):
        self.conn.execute("DELETE FROM sessions WHERE status=?", (SessionStatus.DEAD.value,))
        self.conn.commit()

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            pid=row["pid"],
            window_handle=row["window_handle"],
            favorite_id=row["favorite_id"],
            group_id=row["group_id"],
            label=row["label"],
            shell_type=ShellType(row["shell_type"]),
            working_dir=row["working_dir"],
            spawned_at=datetime.fromisoformat(row["spawned_at"]) if row["spawned_at"] else None,
            status=SessionStatus(row["status"]),
        )

    def close(self):
        self.conn.close()
