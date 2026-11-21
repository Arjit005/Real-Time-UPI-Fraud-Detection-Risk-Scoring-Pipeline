import psycopg2
import os

CONN_STR = os.getenv(
    "SPRING_DATASOURCE_URL",
    "postgres://avnadmin:password@pg-2bc95907-arjit04554-af81.k.aivencloud.com:10456/defaultdb?sslmode=require"
)

try:
    print("[Postgres] Connecting to Aiven PostgreSQL cloud instance...")
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
