import os
print("importing config...", flush=True)
import config
print("importing database...", flush=True)
import database as db
print("init db...", flush=True)
db.init_db()
print("ALL OK", flush=True)
