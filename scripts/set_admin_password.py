"""Change one user's password from the command line.

Usage: set_admin_password.py <username> <new_password>
Run it as the app's service user with CHOREGREMLIN_DATA_DIR set.
"""

import os
import sqlite3
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_DIR)

from werkzeug.security import generate_password_hash  # noqa: E402

import db  # noqa: E402

MIN_PASSWORD_LENGTH = 10


def main(argv):
    if len(argv) != 3:
        print('Usage: set_admin_password.py <username> <new_password>')
        return 1
    username, password = argv[1], argv[2]
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f'The new password must be at least {MIN_PASSWORD_LENGTH} characters. Nothing was changed.')
        return 1
    if not os.path.exists(db.DB_PATH):
        print(f'No database was found at {db.DB_PATH}. Nothing was changed.')
        return 1

    conn = sqlite3.connect(db.DB_PATH)
    try:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            print(f'No user named "{username}" was found. Nothing was changed.')
            return 1
        db._backup_database()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (generate_password_hash(password), row[0]))
        conn.commit()
    finally:
        conn.close()
    print(f'Password updated for {username}.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
