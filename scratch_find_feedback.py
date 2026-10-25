import sqlite3

for search_term in ['CodeForEarth', 'Earth', 'ranim', 'tres bon', 'Avis', 'feedback']:
    print(f'=== Searching for: {search_term} ===')
    for path in ['db.sqlite3', 'docker-data/db.sqlite3']:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            try:
                cur.execute(f'PRAGMA table_info("{t}")')
                cols = [r[1] for r in cur.fetchall()]
                for col in cols:
                    cur.execute(f'SELECT count(*) FROM "{t}" WHERE CAST("{col}" AS TEXT) LIKE "%{search_term}%"')
                    cnt = cur.fetchone()[0]
                    if cnt > 0:
                        print(f'  [{path}] Found {cnt} in {t}.{col}')
            except Exception as e:
                pass
