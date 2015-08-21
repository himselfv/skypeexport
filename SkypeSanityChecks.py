import sqlite3
import datetime

# Runs some tests on Skype database to verify our assumptions about it are true

def assert_no_convoless_messages(conn):
    orphans = conn.execute('SELECT * FROM messages WHERE convo_id is Null')
    for orphan in orphans:
        raise Exception('Orphan message found - no convo_id!')

def assert_no_authorless_messages(conn):
    orphans = conn.execute('SELECT * FROM messages WHERE author is Null OR author = ""')
    for orphan in orphans:
        raise Exception('Authorless message found!')


# Call this to verify the whole package
def db_sanity_checks(conn):
    assert_no_convoless_messages(conn)
    assert_no_authorless_messages(conn)


# You can run this module standalone to test any database you like
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--profile', type=str, required=True, help='Skype profile folder (there could be several for a single windows profile)')
    args = parser.parse_args()

    conn = sqlite3.connect(args.profile+'\main.db')
    conn.row_factory = sqlite3.Row
    db_sanity_checks(conn)
    conn.close()