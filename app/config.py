from __future__ import annotations

from pathlib import Path


ROOT_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = ROOT_DIR / "data"
DB_DIR: Path = DATA_DIR / "db"
DUCKDB_PATH: Path = DB_DIR / "reviews.duckdb"

# Existing source files for initial ingestion/mapping.
SOURCE_CSVS: tuple[Path, ...] = (
    DATA_DIR / "converted_reviews_good.csv",
    DATA_DIR / "converted_reviews_average.csv",
    DATA_DIR / "converted_reviews_bad.csv",
)

# Canonical pipeline input location from PLAN.md.
INPUT_CSV_PATH: Path = DATA_DIR / "input" / "reviews.csv"
