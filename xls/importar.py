#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Importador de calificaciones XLS/XLSX/CSV/HTML a SQLite, usando Pandas.

IMPORTANTE:
Esta versión NO inventa notas por posición. Lee explícitamente las columnas reales
del export de Educaria:

- Alumno: columna "Nombre"
- I:     "Primera Evaluación"  -> subcolumna "FNA" / "Final"
- II:    "Segunda Evaluación"  -> subcolumna "FNA" / "Final"
- III:   "Tercera evaluación"  -> subcolumna "FNA" / "Final"
- F/O:   "Evaluación Final"    -> subcolumna "FNA" / "Final"
         Si no existe Evaluación Final, usa "Notas finales" -> "FN"
         Si tampoco existe, usa la última evaluación disponible.
- E:     "Notas finales"       -> subcolumna "FN" / "Final 1EXTR" cuando existe.

Además:
- No usa LibreOffice.
- No usa Java.
- Es seguro ejecutarlo varias veces: usa UNIQUE + UPSERT.
- Evita la fila falsa "nan".
"""

import argparse
import hashlib
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


DEFAULT_DB = "grades.sqlite"
DEFAULT_TEACHER_USERNAME = "jocarsa"


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def normalize_text(value: Any) -> str:
    if is_empty(value):
        return ""
    text = str(value).strip()
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = strip_accents(text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(value: str) -> str:
    text = strip_accents(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "sin-nombre"


def student_key(fullname: str) -> str:
    key = norm_key(fullname)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def parse_grade(value: Any) -> Optional[float]:
    if is_empty(value):
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        if 0 <= num <= 10:
            return round(num, 2)
        return None

    text = normalize_text(value).upper().replace(",", ".")

    # NP/NC deben contar como suspenso.
    # Los guardamos como 0 para que la web los compute como < 5.
    if text in {
        "NP", "N/P", "NO PRESENTADO", "NO PRESENTADA",
        "NC", "N/C", "NO CALIFICADO", "NO CALIFICADA"
    }:
        return 0.0

    # NE o guion se consideran sin dato evaluable.
    if text in {"NE", "N.E.", "-"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        num = float(match.group(0))
    except ValueError:
        return None

    if 0 <= num <= 10:
        return round(num, 2)

    return None


def read_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    """
    Lee el archivo conservando filas de cabecera reales con header=None.
    """
    suffix = path.suffix.lower()
    errors: List[str] = []

    if suffix == ".xls":
        try:
            return pd.read_excel(path, sheet_name=None, header=None, engine="xlrd")
        except Exception as exc:
            errors.append(f"xlrd: {exc}")

    if suffix == ".xlsx":
        try:
            return pd.read_excel(path, sheet_name=None, header=None, engine="openpyxl")
        except Exception as exc:
            errors.append(f"openpyxl: {exc}")

    # HTML disfrazado de XLS
    try:
        tables = pd.read_html(path)
        if tables:
            return {f"table_{i+1}": df for i, df in enumerate(tables)}
    except Exception as exc:
        errors.append(f"read_html: {exc}")

    # CSV / texto
    for sep in [";", ",", "\t", "|"]:
        for enc in ["utf-8", "latin1"]:
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, header=None, engine="python")
                if df.shape[1] > 1:
                    return {"csv": df}
            except Exception as exc:
                errors.append(f"read_csv sep={sep!r} enc={enc}: {exc}")

    raise RuntimeError(
        f"No he podido leer {path.name}. Errores:\n- " + "\n- ".join(errors)
    )


def get_sheet(sheets: Dict[str, pd.DataFrame], wanted: str) -> Optional[pd.DataFrame]:
    wanted_key = norm_key(wanted)
    for name, df in sheets.items():
        if norm_key(name) == wanted_key:
            return df
    for name, df in sheets.items():
        if wanted_key in norm_key(name):
            return df
    return None


def data_sheet(sheets: Dict[str, pd.DataFrame]) -> Tuple[str, pd.DataFrame]:
    extra = get_sheet(sheets, "Extra")
    if extra is not None:
        return "Extra", extra

    best_name = ""
    best_df = None
    best_score = -1

    for name, df in sheets.items():
        if df.empty:
            continue
        score = df.shape[0] * df.shape[1]
        flat = " ".join(norm_key(x) for x in df.head(10).fillna("").values.flatten())
        if "nombre" in flat:
            score += 10000
        if "primera evaluacion" in flat or "segunda evaluacion" in flat:
            score += 5000
        if score > best_score:
            best_name = name
            best_df = df
            best_score = score

    if best_df is None:
        raise RuntimeError("No se ha encontrado una hoja de datos.")

    return best_name, best_df


def extract_subject_full_name(sheets: Dict[str, pd.DataFrame]) -> str:
    info = get_sheet(sheets, "Info")
    if info is None or info.empty:
        return ""

    for _, row in info.iterrows():
        cells = [normalize_text(v) for v in row.tolist()]
        keys = [norm_key(v) for v in cells]

        for i, key in enumerate(keys):
            if key in {"materia", "modulo", "asignatura"} or "materia" in key or "modulo" in key:
                for j in range(i + 1, len(cells)):
                    if cells[j]:
                        return cells[j]

    return ""


def find_header_positions(df: pd.DataFrame) -> Tuple[int, int, int, int]:
    """
    Devuelve:
    - row_group: fila con "Primera Evaluación", "Segunda Evaluación", etc.
    - row_code: fila con NTA/RCA/FNA/FN.
    - row_desc: fila con Nota/Recuperación/Final.
    - student_col: columna Nombre.
    """
    row_group = -1
    row_code = -1
    row_desc = -1
    student_col = -1

    max_scan = min(15, len(df))

    for r in range(max_scan):
        values = [norm_key(v) for v in df.iloc[r].tolist()]
        for c, key in enumerate(values):
            if key == "nombre":
                student_col = c

        joined = " ".join(values)

        if (
            "primera evaluacion" in joined
            or "segunda evaluacion" in joined
            or "tercera evaluacion" in joined
            or "evaluacion final" in joined
            or "notas finales" in joined
        ):
            row_group = r

        if "fna" in values or "nta" in values or "fn" in values:
            row_code = r

        if "final" in values or "nota" in values or "recuperacion" in values:
            # Normalmente es la fila inferior a NTA/RCA/FNA.
            if r > row_code:
                row_desc = r

    if student_col < 0:
        raise RuntimeError("No se ha encontrado la columna 'Nombre'.")

    if row_group < 0 or row_code < 0:
        raise RuntimeError("No se han encontrado las cabeceras de evaluación.")

    if row_desc < 0:
        row_desc = row_code

    return row_group, row_code, row_desc, student_col


def fill_group_names(df: pd.DataFrame, row_group: int) -> Dict[int, str]:
    """
    En Excel las celdas combinadas aparecen como valor en la primera columna del grupo
    y las siguientes columnas aparecen vacías. Esta función propaga el grupo hacia la derecha.
    """
    groups: Dict[int, str] = {}
    current = ""

    for c in range(df.shape[1]):
        raw = normalize_text(df.iat[row_group, c])
        if raw:
            current = raw
        groups[c] = current

    return groups


def column_score_for_eval(group: str, code: str, desc: str, target: str) -> int:
    g = norm_key(group)
    c = norm_key(code)
    d = norm_key(desc)

    score = 0

    if target == "I":
        if "primera evaluacion" in g:
            score += 100
    elif target == "II":
        if "segunda evaluacion" in g:
            score += 100
    elif target == "III":
        if "tercera evaluacion" in g:
            score += 100
    elif target == "F":
        if "evaluacion final" in g:
            score += 100
        elif "notas finales" in g:
            score += 80
    elif target == "E":
        if "notas finales" in g:
            score += 100
        elif "extra" in d or "extr" in d:
            score += 50

    # Elegimos la columna Final, no la columna Nota ni Recuperación.
    if c == "fna":
        score += 40
    elif c == "fn":
        score += 40
    elif d.startswith("final"):
        score += 35
    elif c == "nta" or d == "nota":
        score += 10
    elif c == "rca" or "recuperacion" in d:
        score -= 30

    return score


def detect_eval_columns(df: pd.DataFrame) -> Tuple[int, Dict[str, Optional[int]], Dict[str, Any]]:
    row_group, row_code, row_desc, student_col = find_header_positions(df)
    groups = fill_group_names(df, row_group)

    eval_cols: Dict[str, Optional[int]] = {
        "I": None,
        "II": None,
        "III": None,
        "F": None,
        "E": None,
    }

    debug_candidates: Dict[str, Any] = {}

    for target in eval_cols.keys():
        best_col = None
        best_score = -999

        candidates = []
        for c in range(df.shape[1]):
            group = groups.get(c, "")
            code = normalize_text(df.iat[row_code, c])
            desc = normalize_text(df.iat[row_desc, c])

            score = column_score_for_eval(group, code, desc, target)
            if score > 0:
                candidates.append({
                    "col": c,
                    "excel_col": c + 1,
                    "group": group,
                    "code": code,
                    "desc": desc,
                    "score": score,
                })

            if score > best_score:
                best_score = score
                best_col = c

        if best_score > 0:
            eval_cols[target] = best_col

        debug_candidates[target] = sorted(candidates, key=lambda x: x["score"], reverse=True)[:5]

    # Si no hay evaluación final, usamos la última evaluación disponible.
    if eval_cols["F"] is None:
        for fallback in ["III", "II", "I"]:
            if eval_cols[fallback] is not None:
                eval_cols["F"] = eval_cols[fallback]
                break

    return student_col, eval_cols, {
        "row_group": row_group + 1,
        "row_code": row_code + 1,
        "row_desc": row_desc + 1,
        "student_col": student_col + 1,
        "eval_cols": {k: (v + 1 if v is not None else None) for k, v in eval_cols.items()},
        "candidates": debug_candidates,
    }


def first_student_row(df: pd.DataFrame, student_col: int, after_row: int = 0) -> int:
    """
    Busca la primera fila real de alumnado.
    """
    for r in range(max(after_row, 0), len(df)):
        name = normalize_text(df.iat[r, student_col])
        if not name:
            continue

        key = norm_key(name)

        if key in {"nombre", "alumno", "alumna", "estudiante"}:
            continue

        # Nombres de alumnos: contienen letras y suelen tener longitud razonable.
        if len(name) >= 3 and any(ch.isalpha() for ch in name):
            return r

    return len(df)


def extract_rows(path: Path, sheets: Dict[str, pd.DataFrame]) -> Tuple[str, str, List[Dict[str, Any]], Dict[str, Any]]:
    slug = slugify(path.stem)
    full_name = extract_subject_full_name(sheets)

    sheet_name, df = data_sheet(sheets)

    # Mantener dimensiones reales y NaN como vacío.
    df = df.copy()

    student_col, eval_cols, debug = detect_eval_columns(df)
    start_row = first_student_row(df, student_col, after_row=debug["row_desc"])

    rows: List[Dict[str, Any]] = []

    for r in range(start_row, len(df)):
        fullname = normalize_text(df.iat[r, student_col])

        if not fullname:
            continue

        key = norm_key(fullname)

        # Evitar filas basura.
        if key in {"nan", "nombre", "alumno", "alumna", "estudiante", "total", "media", "promedio"}:
            continue

        if len(fullname) < 3 or not any(ch.isalpha() for ch in fullname):
            continue

        I = parse_grade(df.iat[r, eval_cols["I"]]) if eval_cols["I"] is not None else None
        II = parse_grade(df.iat[r, eval_cols["II"]]) if eval_cols["II"] is not None else None
        III = parse_grade(df.iat[r, eval_cols["III"]]) if eval_cols["III"] is not None else None
        F = parse_grade(df.iat[r, eval_cols["F"]]) if eval_cols["F"] is not None else None
        E = parse_grade(df.iat[r, eval_cols["E"]]) if eval_cols["E"] is not None else None

        # Regla solicitada: F y O iguales.
        O = F

        if all(x is None for x in [I, II, III, F, O, E]):
            continue

        rows.append({
            "student_fullname": fullname,
            "student_key": student_key(fullname),
            "I": I,
            "II": II,
            "III": III,
            "F": F,
            "O": O,
            "E": E,
        })

    debug["sheet_name"] = sheet_name
    debug["first_student_row"] = start_row + 1
    debug["rows_detected"] = len(rows)

    return slug, full_name, rows, debug


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT,
        role TEXT NOT NULL DEFAULT 'teacher',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        full_name TEXT,
        source_filename TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_key TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        I REAL,
        II REAL,
        III REAL,
        F REAL,
        O REAL,
        E REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(student_id, subject_id),
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS import_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_filename TEXT NOT NULL UNIQUE,
        subject_slug TEXT,
        rows_imported INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        message TEXT,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)


def upsert_user(conn: sqlite3.Connection, username: str) -> int:
    conn.execute("""
        INSERT INTO users (username, display_name, role)
        VALUES (?, ?, 'teacher')
        ON CONFLICT(username) DO UPDATE SET
            display_name = excluded.display_name,
            role = excluded.role,
            updated_at = CURRENT_TIMESTAMP
    """, (username, username))
    return int(conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"])


def upsert_subject(conn: sqlite3.Connection, teacher_id: int, slug: str, full_name: str, source_filename: str) -> int:
    conn.execute("""
        INSERT INTO subjects (teacher_id, slug, full_name, source_filename)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            teacher_id = excluded.teacher_id,
            full_name = excluded.full_name,
            source_filename = excluded.source_filename,
            updated_at = CURRENT_TIMESTAMP
    """, (teacher_id, slug, full_name, source_filename))
    return int(conn.execute("SELECT id FROM subjects WHERE slug = ?", (slug,)).fetchone()["id"])


def upsert_student(conn: sqlite3.Connection, full_name: str, key: str) -> int:
    conn.execute("""
        INSERT INTO students (student_key, full_name)
        VALUES (?, ?)
        ON CONFLICT(student_key) DO UPDATE SET
            full_name = excluded.full_name,
            updated_at = CURRENT_TIMESTAMP
    """, (key, full_name))
    return int(conn.execute("SELECT id FROM students WHERE student_key = ?", (key,)).fetchone()["id"])


def upsert_grade(conn: sqlite3.Connection, student_id: int, subject_id: int, row: Dict[str, Any]) -> None:
    conn.execute("""
        INSERT INTO grades (student_id, subject_id, I, II, III, F, O, E)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, subject_id) DO UPDATE SET
            I = excluded.I,
            II = excluded.II,
            III = excluded.III,
            F = excluded.F,
            O = excluded.O,
            E = excluded.E,
            updated_at = CURRENT_TIMESTAMP
    """, (
        student_id,
        subject_id,
        row["I"],
        row["II"],
        row["III"],
        row["F"],
        row["O"],
        row["E"],
    ))


def upsert_import_log(conn: sqlite3.Connection, filename: str, slug: str, rows: int, status: str, message: str = "") -> None:
    conn.execute("""
        INSERT INTO import_log (source_filename, subject_slug, rows_imported, status, message)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_filename) DO UPDATE SET
            subject_slug = excluded.subject_slug,
            rows_imported = excluded.rows_imported,
            status = excluded.status,
            message = excluded.message,
            imported_at = CURRENT_TIMESTAMP
    """, (filename, slug, rows, status, message))


def input_files(input_dir: Path) -> List[Path]:
    allowed = {".xls", ".xlsx", ".csv", ".html", ".htm"}
    result = []
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("~$"):
            continue
        if p.name == Path(__file__).name:
            continue
        if p.suffix.lower() in allowed:
            result.append(p)
    return result


def import_file(conn: sqlite3.Connection, teacher_id: int, path: Path, debug: bool = False) -> int:
    print(f"Importing {path.name} ...")

    sheets = read_sheets(path)
    slug, full_name, rows, dbg = extract_rows(path, sheets)

    subject_id = upsert_subject(conn, teacher_id, slug, full_name, path.name)

    for row in rows:
        student_id = upsert_student(conn, row["student_fullname"], row["student_key"])
        upsert_grade(conn, student_id, subject_id, row)

    upsert_import_log(conn, path.name, slug, len(rows), "ok", "")

    print(f"  Subject: {full_name or slug}")
    print(f"  Slug: {slug}")
    print(f"  Rows imported/updated: {len(rows)}")
    print(f"  Columns: I={dbg['eval_cols']['I']} II={dbg['eval_cols']['II']} III={dbg['eval_cols']['III']} F/O={dbg['eval_cols']['F']} E={dbg['eval_cols']['E']}")

    if debug:
        print(f"  Debug: sheet={dbg['sheet_name']} header_rows={dbg['row_group']},{dbg['row_code']},{dbg['row_desc']} first_student_row={dbg['first_student_row']}")

    return len(rows)


def print_summary(conn: sqlite3.Connection) -> None:
    print()
    print("Summary")
    print("-------")
    for table in ["users", "subjects", "students", "grades"]:
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        print(f"{table}: {n}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=".", help="Carpeta con los XLS/XLSX")
    parser.add_argument("--db", default=DEFAULT_DB, help="Base SQLite")
    parser.add_argument("--teacher", default=DEFAULT_TEACHER_USERNAME, help="Usuario profesor")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Borra la base de datos antes de importar")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    db_path = Path(args.db).resolve()

    if args.reset and db_path.exists():
        db_path.unlink()

    files = input_files(input_dir)

    if not files:
        print(f"No hay archivos de entrada en {input_dir}")
        return 0

    conn = connect_db(db_path)
    init_schema(conn)
    teacher_id = upsert_user(conn, args.teacher)

    ok = 0
    failed = 0

    for path in files:
        try:
            with conn:
                import_file(conn, teacher_id, path, debug=args.debug)
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR importing {path.name}: {exc}", file=sys.stderr)
            try:
                with conn:
                    upsert_import_log(conn, path.name, slugify(path.stem), 0, "error", str(exc)[:2000])
            except Exception:
                pass
            if args.stop_on_error:
                conn.close()
                return 1

    print_summary(conn)
    print()
    print(f"Finished. OK: {ok}. Failed: {failed}. DB: {db_path}")

    conn.close()
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
