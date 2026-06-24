"""SQLite persistence for projects and parsed navigation data."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from xpostmaps.core.legend_utils import legend_from_dict, legend_to_dict
from xpostmaps.core.navplan_catalog_utils import (
    navplan_catalog_from_json,
    navplan_catalog_to_json,
)
from xpostmaps.core.preplot_catalog_utils import catalog_from_json, catalog_to_json
from xpostmaps.core.sequence_utils import nav_cache_from_json, nav_cache_to_json
from xpostmaps.core.models import (
    DisplayMode,
    GeoBounds,
    LineSegment,
    LineSequence,
    MapData,
    PositionRecord,
    PostmapInfo,
    ProjectSettings,
    RecordType,
    SurveyBounds,
    SurveyPerimeter,
)


class Database:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "data" / "xpostmaps.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                p111_p190_dir TEXT DEFAULT '',
                overlay_dir TEXT DEFAULT '',
                preplots_dir TEXT DEFAULT '',
                display_mode TEXT DEFAULT 'lines',
                show_source INTEGER DEFAULT 1,
                show_vessel INTEGER DEFAULT 1,
                show_overlay INTEGER DEFAULT 1,
                show_preplots INTEGER DEFAULT 1,
                postmap_info_json TEXT DEFAULT '{}',
                bounds_json TEXT DEFAULT '{}',
                stats_json TEXT DEFAULT '{}',
                source_files_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                line_name TEXT NOT NULL,
                record_type TEXT NOT NULL,
                direction INTEGER DEFAULT 1,
                xs_json TEXT NOT NULL,
                ys_json TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_segments_project
                ON segments(project_id);

            CREATE TABLE IF NOT EXISTS line_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                seq_key TEXT NOT NULL,
                file_name TEXT NOT NULL,
                sequence_no TEXT NOT NULL,
                line_name TEXT NOT NULL,
                subline TEXT DEFAULT '',
                line_direction TEXT DEFAULT '',
                first_sp INTEGER NOT NULL,
                last_sp INTEGER NOT NULL,
                record_type TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, seq_key)
            );

            CREATE INDEX IF NOT EXISTS idx_sequences_project
                ON line_sequences(project_id);

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                record_type TEXT NOT NULL,
                sequence_no TEXT DEFAULT '',
                line_name TEXT DEFAULT '',
                line_direction TEXT DEFAULT '',
                subline TEXT DEFAULT '',
                point_num INTEGER NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                depth REAL,
                latitude TEXT DEFAULT '',
                longitude TEXT DEFAULT '',
                vessel_id TEXT DEFAULT '',
                source_id TEXT DEFAULT '',
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_positions_project
                ON positions(project_id);

            CREATE INDEX IF NOT EXISTS idx_positions_sequence_lookup
                ON positions(project_id, file_name, sequence_no, line_name);

            CREATE TABLE IF NOT EXISTS survey_perimeters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                name TEXT NOT NULL,
                xs_json TEXT NOT NULL,
                ys_json TEXT NOT NULL,
                latitudes_json TEXT DEFAULT '[]',
                longitudes_json TEXT DEFAULT '[]',
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_survey_perimeters_project
                ON survey_perimeters(project_id);
            """
        )
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(projects)")}
        if "logo_path" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN logo_path TEXT DEFAULT ''")
        if "legend_config_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN legend_config_json TEXT DEFAULT '{}'"
            )
        if "geo_bounds_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN geo_bounds_json TEXT DEFAULT '{}'"
            )
        if "nav_files_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN nav_files_json TEXT DEFAULT '[]'"
            )
        if "preplot_files_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN preplot_files_json TEXT DEFAULT '[]'"
            )
        if "nav_file_cache_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN nav_file_cache_json TEXT DEFAULT '{}'"
            )
        if "nav_files_explicit" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN nav_files_explicit INTEGER DEFAULT 0"
            )
        if "preplot_files_explicit" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN preplot_files_explicit INTEGER DEFAULT 0"
            )
        if "preplot_catalog_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN preplot_catalog_json TEXT DEFAULT '[]'"
            )
        if "minimap_view_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN minimap_view_json TEXT DEFAULT '{}'"
            )
        if "navplan_files_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN navplan_files_json TEXT DEFAULT '[]'"
            )
        if "navplan_files_explicit" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN navplan_files_explicit INTEGER DEFAULT 0"
            )
        if "navplans_dir" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN navplans_dir TEXT DEFAULT ''"
            )
        if "navplan_catalog_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN navplan_catalog_json TEXT DEFAULT '[]'"
            )
        if "map_view_json" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN map_view_json TEXT DEFAULT '{}'"
            )
        if "postplot_4d_baseline" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN postplot_4d_baseline TEXT DEFAULT 'navplan'"
            )

        seg_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(segments)")}
        if "sequence_id" not in seg_cols:
            self._conn.execute("ALTER TABLE segments ADD COLUMN sequence_id TEXT DEFAULT ''")
        if "file_name" not in seg_cols:
            self._conn.execute("ALTER TABLE segments ADD COLUMN file_name TEXT DEFAULT ''")
        if "sequence_no" not in seg_cols:
            self._conn.execute("ALTER TABLE segments ADD COLUMN sequence_no TEXT DEFAULT ''")
        if "line_direction" not in seg_cols:
            self._conn.execute("ALTER TABLE segments ADD COLUMN line_direction TEXT DEFAULT ''")

        seq_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(line_sequences)")}
        if "subline" not in seq_cols:
            self._conn.execute("ALTER TABLE line_sequences ADD COLUMN subline TEXT DEFAULT ''")

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_perimeters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                name TEXT NOT NULL,
                xs_json TEXT NOT NULL,
                ys_json TEXT NOT NULL,
                latitudes_json TEXT DEFAULT '[]',
                longitudes_json TEXT DEFAULT '[]',
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_survey_perimeters_project
                ON survey_perimeters(project_id)
            """
        )

        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def delete_project(self, name: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM projects WHERE name = ?",
            (name.strip(),),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_project(self, settings: ProjectSettings, map_data: MapData) -> int:
        started = time.perf_counter()
        now = self._now()
        # When positions are already persisted and were not loaded/modified in
        # memory, leave the (potentially huge) positions table untouched. This
        # makes saves fast and prevents accidentally wiping stored positions.
        skip_positions = bool(map_data.positions_persisted) and not map_data.positions
        postmap_json = json.dumps(map_data.postmap_info.__dict__, default=str)
        bounds_json = json.dumps(map_data.bounds.__dict__)
        geo_bounds_json = json.dumps(map_data.geo_bounds.__dict__)
        stats_json = json.dumps(map_data.stats)
        files_json = json.dumps(map_data.source_files)
        nav_files_json = json.dumps(settings.nav_files)
        preplot_files_json = json.dumps(settings.preplot_files)
        preplot_catalog_json = json.dumps(catalog_to_json(settings.preplot_catalog))
        navplan_files_json = json.dumps(settings.navplan_files)
        navplan_catalog_json = json.dumps(
            navplan_catalog_to_json(settings.navplan_catalog)
        )
        legend_json = json.dumps(legend_to_dict(settings.legend_config))
        nav_cache_json = json.dumps(nav_cache_to_json(map_data.nav_file_cache))
        minimap_view_json = json.dumps(settings.minimap_view)
        map_view_json = json.dumps(settings.map_view)

        row = self._conn.execute(
            "SELECT id FROM projects WHERE name = ?", (settings.name,)
        ).fetchone()

        if row:
            project_id = row["id"]
            parsed_nav_names = {
                str(name)
                for name in map_data.stats.get("nav_files_parsed_names", [])
                if str(name)
            }
            active_nav_names = {
                str(name)
                for name in map_data.stats.get("nav_files_active_names", [])
                if str(name)
            }
            incremental_nav = bool(active_nav_names) and bool(
                map_data.stats.get("nav_files_skipped", 0)
            )
            self._conn.execute(
                """
                UPDATE projects SET
                    p111_p190_dir=?, overlay_dir=?, preplots_dir=?,
                    display_mode=?, show_source=?, show_vessel=?,
                    show_overlay=?, show_preplots=?,
                    postmap_info_json=?, bounds_json=?, geo_bounds_json=?,
                    stats_json=?, source_files_json=?, nav_files_json=?,
                    preplot_files_json=?, nav_file_cache_json=?, logo_path=?,
                    legend_config_json=?, nav_files_explicit=?, preplot_files_explicit=?,
                    preplot_catalog_json=?, minimap_view_json=?,
                    navplan_files_json=?, navplan_files_explicit=?,
                    navplans_dir=?, navplan_catalog_json=?, map_view_json=?,
                    postplot_4d_baseline=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    settings.p111_p190_dir,
                    settings.overlay_dir,
                    settings.preplots_dir,
                    settings.display_mode.value,
                    int(settings.show_source),
                    int(settings.show_vessel),
                    int(settings.show_overlay),
                    int(settings.show_preplots),
                    postmap_json,
                    bounds_json,
                    geo_bounds_json,
                    stats_json,
                    files_json,
                    nav_files_json,
                    preplot_files_json,
                    nav_cache_json,
                    settings.logo_path,
                    legend_json,
                    int(settings.nav_files_explicit),
                    int(settings.preplot_files_explicit),
                    preplot_catalog_json,
                    minimap_view_json,
                    navplan_files_json,
                    int(settings.navplan_files_explicit),
                    settings.navplans_dir,
                    navplan_catalog_json,
                    map_view_json,
                    settings.postplot_4d_baseline,
                    now,
                    project_id,
                ),
            )
            if incremental_nav:
                self._delete_incremental_nav_rows(
                    int(project_id),
                    active_nav_names,
                    parsed_nav_names,
                    delete_positions=not skip_positions,
                )
                self._conn.execute(
                    "DELETE FROM segments WHERE project_id=? AND category IN ('overlay', 'preplot', 'navplan')",
                    (project_id,),
                )
            else:
                self._conn.execute("DELETE FROM segments WHERE project_id=?", (project_id,))
                self._conn.execute("DELETE FROM line_sequences WHERE project_id=?", (project_id,))
                if not skip_positions:
                    self._conn.execute("DELETE FROM positions WHERE project_id=?", (project_id,))
            self._conn.execute("DELETE FROM survey_perimeters WHERE project_id=?", (project_id,))
        else:
            cursor = self._conn.execute(
                """
                INSERT INTO projects (
                    name, p111_p190_dir, overlay_dir, preplots_dir,
                    display_mode, show_source, show_vessel, show_overlay, show_preplots,
                    postmap_info_json, bounds_json, geo_bounds_json, stats_json,
                    source_files_json, nav_files_json, preplot_files_json,
                    nav_file_cache_json, logo_path, legend_config_json,
                    nav_files_explicit, preplot_files_explicit, preplot_catalog_json,
                    minimap_view_json, navplan_files_json, navplan_files_explicit,
                    navplans_dir, navplan_catalog_json, map_view_json,
                    postplot_4d_baseline,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    settings.name,
                    settings.p111_p190_dir,
                    settings.overlay_dir,
                    settings.preplots_dir,
                    settings.display_mode.value,
                    int(settings.show_source),
                    int(settings.show_vessel),
                    int(settings.show_overlay),
                    int(settings.show_preplots),
                    postmap_json,
                    bounds_json,
                    geo_bounds_json,
                    stats_json,
                    files_json,
                    nav_files_json,
                    preplot_files_json,
                    nav_cache_json,
                    settings.logo_path,
                    legend_json,
                    int(settings.nav_files_explicit),
                    int(settings.preplot_files_explicit),
                    preplot_catalog_json,
                    minimap_view_json,
                    navplan_files_json,
                    int(settings.navplan_files_explicit),
                    settings.navplans_dir,
                    navplan_catalog_json,
                    map_view_json,
                    settings.postplot_4d_baseline,
                    now,
                    now,
                ),
            )
            project_id = cursor.lastrowid
            incremental_nav = False
            parsed_nav_names = set()

        main_segments = (
            [seg for seg in map_data.segments if seg.file_name in parsed_nav_names]
            if incremental_nav
            else map_data.segments
        )
        sequences = (
            [seq for seq in map_data.sequences if seq.file_name in parsed_nav_names]
            if incremental_nav
            else map_data.sequences
        )
        positions = (
            [pos for pos in map_data.positions if pos.file_name in parsed_nav_names]
            if incremental_nav
            else map_data.positions
        )

        self._save_segments(project_id, "main", main_segments)
        self._save_segments(project_id, "overlay", map_data.overlay_segments)
        self._save_segments(project_id, "preplot", map_data.preplot_segments)
        self._save_segments(project_id, "navplan", map_data.navplan_segments)
        self._save_sequences(project_id, sequences)
        if not skip_positions:
            self._save_positions(project_id, positions)
        self._save_survey_perimeters(project_id, map_data.survey_perimeters)
        self._conn.commit()
        elapsed_ms = (time.perf_counter() - started) * 1000
        mode = "incremental-nav" if incremental_nav else "full"
        print(f"[xPostMaps timing] DB save {mode}: {elapsed_ms:.1f} ms")
        return int(project_id)

    def save_project_metadata(self, settings: ProjectSettings, map_data: MapData) -> int:
        """Persist UI metadata (legend, minimap, display flags) without touching geometry.

        Project information, bounds, stats, and nav cache are intentionally
        excluded so legend/minimap autosave cannot overwrite user-edited
        postmap fields or parsed survey data.
        """
        row = self._conn.execute(
            "SELECT id FROM projects WHERE name = ?", (settings.name,)
        ).fetchone()
        if row is None:
            return self.save_project(settings, map_data)

        project_id = int(row["id"])
        now = self._now()
        self._conn.execute(
            """
            UPDATE projects SET
                display_mode=?, show_source=?, show_vessel=?,
                show_overlay=?, show_preplots=?,
                logo_path=?, legend_config_json=?, minimap_view_json=?,
                map_view_json=?, postplot_4d_baseline=?, updated_at=?
            WHERE id=?
            """,
            (
                settings.display_mode.value,
                int(settings.show_source),
                int(settings.show_vessel),
                int(settings.show_overlay),
                int(settings.show_preplots),
                settings.logo_path,
                json.dumps(legend_to_dict(settings.legend_config)),
                json.dumps(settings.minimap_view),
                json.dumps(settings.map_view),
                settings.postplot_4d_baseline,
                now,
                project_id,
            ),
        )
        self._conn.commit()
        return project_id

    def _save_segments(
        self, project_id: int, category: str, segments: list[LineSegment]
    ) -> None:
        rows = [
            (
                project_id,
                category,
                seg.line_name,
                seg.record_type.value,
                seg.direction,
                json.dumps(seg.xs),
                json.dumps(seg.ys),
                seg.sequence_id,
                seg.file_name,
                seg.sequence_no,
                seg.line_direction,
            )
            for seg in segments
        ]
        if rows:
            self._conn.executemany(
                """
                INSERT INTO segments (
                    project_id, category, line_name, record_type,
                    direction, xs_json, ys_json,
                    sequence_id, file_name, sequence_no, line_direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _existing_nav_file_names(self, project_id: int) -> set[str]:
        rows = self._conn.execute(
            """
            SELECT file_name FROM positions WHERE project_id=?
            UNION
            SELECT file_name FROM line_sequences WHERE project_id=?
            UNION
            SELECT file_name FROM segments WHERE project_id=? AND category='main'
            """,
            (project_id, project_id, project_id),
        ).fetchall()
        return {row["file_name"] for row in rows if row["file_name"]}

    def _delete_incremental_nav_rows(
        self,
        project_id: int,
        active_names: set[str],
        parsed_names: set[str],
        *,
        delete_positions: bool,
    ) -> None:
        replace_names = (self._existing_nav_file_names(project_id) - active_names) | parsed_names
        if not replace_names:
            return
        placeholders = ",".join("?" for _ in replace_names)
        params = [project_id, *sorted(replace_names)]
        self._conn.execute(
            f"DELETE FROM segments WHERE project_id=? AND category='main' AND file_name IN ({placeholders})",
            params,
        )
        self._conn.execute(
            f"DELETE FROM line_sequences WHERE project_id=? AND file_name IN ({placeholders})",
            params,
        )
        if delete_positions:
            self._conn.execute(
                f"DELETE FROM positions WHERE project_id=? AND file_name IN ({placeholders})",
                params,
            )

    def _save_sequences(self, project_id: int, sequences: list[LineSequence]) -> None:
        rows = [
            (
                project_id,
                seq.seq_id,
                seq.file_name,
                seq.sequence_no,
                seq.line_name,
                seq.subline,
                seq.line_direction,
                seq.first_sp,
                seq.last_sp,
                seq.record_type.value,
            )
            for seq in sequences
        ]
        if rows:
            self._conn.executemany(
                """
                INSERT INTO line_sequences (
                    project_id, seq_key, file_name, sequence_no, line_name,
                    subline, line_direction, first_sp, last_sp, record_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _save_positions(self, project_id: int, positions: list[PositionRecord]) -> None:
        rows = [
            (
                project_id,
                pos.file_name,
                pos.record_type.value,
                pos.sequence_no,
                pos.line_name,
                pos.line_direction,
                pos.subline,
                pos.point_num,
                pos.x,
                pos.y,
                pos.depth,
                pos.latitude,
                pos.longitude,
                pos.vessel_id,
                pos.source_id,
            )
            for pos in positions
        ]
        if rows:
            self._conn.executemany(
                """
                INSERT INTO positions (
                    project_id, file_name, record_type, sequence_no, line_name,
                    line_direction, subline, point_num, x, y, depth,
                    latitude, longitude, vessel_id, source_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _save_survey_perimeters(
        self, project_id: int, perimeters: list[SurveyPerimeter]
    ) -> None:
        rows = [
            (
                project_id,
                perimeter.file_name,
                perimeter.name,
                json.dumps(perimeter.xs),
                json.dumps(perimeter.ys),
                json.dumps(perimeter.latitudes),
                json.dumps(perimeter.longitudes),
            )
            for perimeter in perimeters
        ]
        if rows:
            self._conn.executemany(
                """
                INSERT INTO survey_perimeters (
                    project_id, file_name, name, xs_json, ys_json,
                    latitudes_json, longitudes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def load_project(
        self, name: str, with_positions: bool = False
    ) -> tuple[ProjectSettings, MapData] | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None

        nav_files = []
        if "nav_files_json" in row.keys():
            nav_files = json.loads(row["nav_files_json"] or "[]")
        preplot_files = []
        if "preplot_files_json" in row.keys():
            preplot_files = json.loads(row["preplot_files_json"] or "[]")

        nav_files_explicit = False
        if "nav_files_explicit" in row.keys():
            nav_files_explicit = bool(row["nav_files_explicit"])
        preplot_files_explicit = False
        if "preplot_files_explicit" in row.keys():
            preplot_files_explicit = bool(row["preplot_files_explicit"])
        preplot_catalog = []
        if "preplot_catalog_json" in row.keys():
            preplot_catalog = catalog_from_json(
                json.loads(row["preplot_catalog_json"] or "[]")
            )
        navplan_files = []
        if "navplan_files_json" in row.keys():
            navplan_files = json.loads(row["navplan_files_json"] or "[]")
        navplan_files_explicit = False
        if "navplan_files_explicit" in row.keys():
            navplan_files_explicit = bool(row["navplan_files_explicit"])
        navplan_catalog = []
        if "navplan_catalog_json" in row.keys():
            navplan_catalog = navplan_catalog_from_json(
                json.loads(row["navplan_catalog_json"] or "[]")
            )

        settings = ProjectSettings(
            name=row["name"],
            p111_p190_dir=row["p111_p190_dir"] or "",
            nav_files=nav_files,
            nav_files_explicit=nav_files_explicit or bool(nav_files),
            preplot_files=preplot_files,
            preplot_files_explicit=preplot_files_explicit or bool(preplot_files),
            preplots_dir=row["preplots_dir"] or "",
            preplot_catalog=preplot_catalog,
            navplan_files=navplan_files,
            navplan_files_explicit=navplan_files_explicit or bool(navplan_files),
            navplans_dir=(row["navplans_dir"] or "") if "navplans_dir" in row.keys() else "",
            navplan_catalog=navplan_catalog,
            overlay_dir=row["overlay_dir"] or "",
            display_mode=DisplayMode(row["display_mode"]),
            show_source=bool(row["show_source"]),
            show_vessel=bool(row["show_vessel"]),
            show_overlay=bool(row["show_overlay"]),
            show_preplots=bool(row["show_preplots"]),
            logo_path=row["logo_path"] if "logo_path" in row.keys() else "",
            legend_config=legend_from_dict(
                json.loads(row["legend_config_json"] or "{}")
                if "legend_config_json" in row.keys()
                else {}
            ),
            minimap_view=json.loads(row["minimap_view_json"] or "{}")
            if "minimap_view_json" in row.keys()
            else {},
            map_view=json.loads(row["map_view_json"] or "{}")
            if "map_view_json" in row.keys()
            else {},
            postplot_4d_baseline=(
                row["postplot_4d_baseline"]
                if "postplot_4d_baseline" in row.keys()
                else "navplan"
            )
            or "navplan",
        )

        postmap_dict = json.loads(row["postmap_info_json"] or "{}")
        field_names = [k for k in PostmapInfo.__dataclass_fields__ if k != "extra"]
        postmap_info = PostmapInfo(
            **{k: postmap_dict.get(k, "") for k in field_names}
        )
        postmap_info.extra = {
            k: v for k, v in postmap_dict.items() if k not in field_names
        }

        bounds_dict = json.loads(row["bounds_json"] or "{}")
        bounds = SurveyBounds(**bounds_dict) if bounds_dict else SurveyBounds()
        geo_dict = json.loads(row["geo_bounds_json"] or "{}") if "geo_bounds_json" in row.keys() else {}
        geo_bounds = GeoBounds(**geo_dict) if geo_dict else GeoBounds()

        project_id = row["id"]
        # Positions (often >1M rows) are not needed for rendering — only for
        # incremental re-parsing. Skip building them on load for fast project
        # open; they are fetched on demand via ``load_positions`` before a parse.
        if with_positions:
            positions = self._load_positions(project_id)
            positions_persisted = False
        else:
            positions = []
            has_positions = self._conn.execute(
                "SELECT 1 FROM positions WHERE project_id=? LIMIT 1", (project_id,)
            ).fetchone()
            positions_persisted = has_positions is not None
        map_data = MapData(
            segments=self._load_segments(project_id, "main"),
            overlay_segments=self._load_segments(project_id, "overlay"),
            preplot_segments=self._load_segments(project_id, "preplot"),
            navplan_segments=self._load_segments(project_id, "navplan"),
            sequences=self._load_sequences(project_id),
            positions=positions,
            positions_persisted=positions_persisted,
            bounds=bounds,
            geo_bounds=geo_bounds,
            postmap_info=postmap_info,
            source_files=json.loads(row["source_files_json"] or "[]"),
            nav_file_cache=nav_cache_from_json(
                json.loads(row["nav_file_cache_json"] or "{}")
                if "nav_file_cache_json" in row.keys()
                else {}
            ),
            survey_perimeters=self._load_survey_perimeters(project_id),
            stats=json.loads(row["stats_json"] or "{}"),
        )
        return settings, map_data

    def get_project_id(self, name: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM projects WHERE name = ?", (name.strip(),)
        ).fetchone()
        return int(row["id"]) if row else None

    def load_positions(self, name: str) -> list[PositionRecord]:
        """Fetch full position records for a project on demand (re-parse only)."""
        project_id = self.get_project_id(name)
        if project_id is None:
            return []
        return self._load_positions(project_id)

    def delete_sequence_groups(self, project_id: int, group_ids: list[str]) -> None:
        if not group_ids:
            return
        for group_id in group_ids:
            parts = group_id.split("|")
            if len(parts) >= 3:
                file_name, sequence_no, line_name = parts[0], parts[1], parts[2]
                self._conn.execute(
                    """
                    DELETE FROM positions
                    WHERE project_id=? AND file_name=? AND sequence_no=? AND line_name=?
                    """,
                    (project_id, file_name, sequence_no, line_name),
                )
                self._conn.execute(
                    """
                    DELETE FROM segments
                    WHERE project_id=? AND category='main' AND file_name=?
                      AND sequence_no=? AND line_name=?
                    """,
                    (project_id, file_name, sequence_no, line_name),
                )
            prefix = f"{group_id}|"
            self._conn.execute(
                """
                DELETE FROM line_sequences
                WHERE project_id=? AND (seq_key=? OR seq_key LIKE ?)
                """,
                (project_id, group_id, prefix + "%"),
            )
            self._conn.execute(
                """
                DELETE FROM segments
                WHERE project_id=? AND category='main'
                  AND (sequence_id=? OR sequence_id LIKE ?)
                """,
                (project_id, group_id, prefix + "%"),
            )
        self._conn.commit()

    def _load_segments(self, project_id: int, category: str) -> list[LineSegment]:
        rows = self._conn.execute(
            """
            SELECT line_name, record_type, direction, xs_json, ys_json,
                   sequence_id, file_name, sequence_no, line_direction
            FROM segments WHERE project_id=? AND category=?
            ORDER BY id
            """,
            (project_id, category),
        ).fetchall()
        segments: list[LineSegment] = []
        for row in rows:
            segments.append(
                LineSegment(
                    line_name=row["line_name"],
                    record_type=RecordType(row["record_type"]),
                    direction=row["direction"],
                    xs=json.loads(row["xs_json"]),
                    ys=json.loads(row["ys_json"]),
                    sequence_id=row["sequence_id"] or "",
                    file_name=row["file_name"] or "",
                    sequence_no=row["sequence_no"] or "",
                    line_direction=row["line_direction"] or "",
                )
            )
        return segments

    def _load_sequences(self, project_id: int) -> list[LineSequence]:
        rows = self._conn.execute(
            """
            SELECT
                seq_key,
                file_name,
                sequence_no,
                line_name,
                COALESCE(
                    NULLIF(subline, ''),
                    (
                        SELECT p.subline
                        FROM positions p
                        WHERE p.project_id = line_sequences.project_id
                          AND p.file_name = line_sequences.file_name
                          AND p.sequence_no = line_sequences.sequence_no
                          AND p.line_name = line_sequences.line_name
                          AND p.subline <> ''
                        LIMIT 1
                    ),
                    ''
                ) AS subline,
                line_direction,
                first_sp,
                last_sp,
                record_type
            FROM line_sequences WHERE project_id=?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        return [
            LineSequence(
                seq_id=row["seq_key"],
                file_name=row["file_name"],
                sequence_no=row["sequence_no"],
                line_name=row["line_name"],
                subline=row["subline"] or "",
                line_direction=row["line_direction"] or "",
                first_sp=row["first_sp"],
                last_sp=row["last_sp"],
                record_type=RecordType(row["record_type"]),
            )
            for row in rows
        ]

    def _load_positions(self, project_id: int) -> list[PositionRecord]:
        rows = self._conn.execute(
            """
            SELECT file_name, record_type, sequence_no, line_name, line_direction,
                   subline, point_num, x, y, depth, latitude, longitude,
                   vessel_id, source_id
            FROM positions WHERE project_id=?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        return [
            PositionRecord(
                file_name=row["file_name"],
                record_type=RecordType(row["record_type"]),
                line_name=row["line_name"] or "",
                vessel_id=row["vessel_id"] or "",
                source_id=row["source_id"] or "",
                point_num=row["point_num"],
                x=row["x"],
                y=row["y"],
                depth=row["depth"],
                latitude=row["latitude"] or "",
                longitude=row["longitude"] or "",
                sequence_no=row["sequence_no"] or "",
                line_direction=row["line_direction"] or "",
                subline=row["subline"] or "",
            )
            for row in rows
        ]

    def _load_survey_perimeters(self, project_id: int) -> list[SurveyPerimeter]:
        rows = self._conn.execute(
            """
            SELECT file_name, name, xs_json, ys_json, latitudes_json, longitudes_json
            FROM survey_perimeters WHERE project_id=?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        perimeters: list[SurveyPerimeter] = []
        for row in rows:
            perimeters.append(
                SurveyPerimeter(
                    file_name=row["file_name"],
                    name=row["name"],
                    xs=json.loads(row["xs_json"] or "[]"),
                    ys=json.loads(row["ys_json"] or "[]"),
                    latitudes=json.loads(row["latitudes_json"] or "[]"),
                    longitudes=json.loads(row["longitudes_json"] or "[]"),
                )
            )
        return perimeters

    def list_projects(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [row["name"] for row in rows]
