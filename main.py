import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import csv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "stg")


def import_employees(csv_path: str) -> int:
    if not os.path.isabs(csv_path):
        base_dir = os.path.dirname(__file__)
        csv_path = os.path.join(base_dir, csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
    )

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            emp_id_raw = row.get('id_employee')
            fio_raw = row.get('fio_employee')
            if not emp_id_raw or not fio_raw:
                continue
            try:
                emp_id = int(str(emp_id_raw).strip())
            except Exception:
                continue
            fio = str(fio_raw).strip()
            if not fio:
                continue
            rows.append({"id": emp_id, "fio": fio})

    if not rows:
        return 0

    with engine.begin() as conn:
        for r in rows:
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), r)

    return len(rows)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reports GUI utilities")
    sub = parser.add_subparsers(dest="cmd")

    p_imp = sub.add_parser("import-employees", help="Import employees from CSV into DB")
    p_imp.add_argument("--csv", default="w.csv")

    args = parser.parse_args()

    if args.cmd == "import-employees":
        count = import_employees(args.csv)
        print(f"Imported/updated: {count}")
    else:
        print("Usage: uv run --env-file .env -- python -m reports_gui.main import-employees --csv w.csv")


if __name__ == "__main__":
    main()
