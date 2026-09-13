import sqlite3

DB = r"e:\University\PDF-Question-Answering-System-RAG\src\data\app.db"
conn = sqlite3.connect(DB)
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print("Tables:", [r[0] for r in cur.fetchall()])

cur = conn.execute("SELECT id, username, email, password_hash FROM users")
rows = cur.fetchall()
print(f"\n{len(rows)} users in DB:")
for r in rows:
    hid = f"{r[0]}"
    uname = r[1][:20] if r[1] else None
    email = (r[2] or "")[:30]
    ph = str(r[3])[:60] if r[3] is not None else None
    is_bcrypt = ph is not None and (ph.startswith("$2b$") or ph.startswith("$2a$"))
    print(f"  id={hid:>3} user={uname!r:<22} email={email!r:<32} hash={ph!r:<62} bcrypt={is_bcrypt}")

all_bcrypt = all(
    (ph is None) or ph.startswith("$2b$") or ph.startswith("$2a$")
    for (_id, _u, _e, ph) in rows
)
print(f"\nAll stored password_hash values are bcrypt: {all_bcrypt}")
conn.close()
