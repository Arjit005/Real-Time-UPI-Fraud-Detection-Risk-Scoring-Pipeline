import psycopg2
import os
import sys
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

CONN_STR = os.getenv("SPRING_DATASOURCE_URL") or os.getenv("DATABASE_URL")
if not CONN_STR:
    print("[Error] Missing required environment variable: SPRING_DATASOURCE_URL or DATABASE_URL")
    sys.exit(1)

try:
    print("[Postgres] Connecting to PostgreSQL database...")
    conn = psycopg2.connect(CONN_STR)
    cur = conn.cursor()

    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"[Postgres] Connected successfully!\nPostgreSQL Version: {version}\n")

    init_sql_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "postgres", "init.sql"))
    print(f"[Postgres] Executing schema init from: {init_sql_path}")
    with open(init_sql_path, "r") as f:
        sql = f.read()
    
    cur.execute(sql)
    conn.commit()
    print("[Postgres] Table 'transactions' and indices created/verified successfully!")

    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'transactions';")
    cols = cur.fetchall()
    print("\nVerified Columns in 'transactions' table:")
    for col in cols:
        print(f"  - {col[0]} ({col[1]})")

    cur.close()
    conn.close()
    print("\n[Postgres] Connection closed cleanly.")
except Exception as e:
    print(f"[Error] Failed: {e}")
    sys.exit(1)
