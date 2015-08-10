import argparse
import sqlite3
import sys

parser = argparse.ArgumentParser(description='Merges one Skype database into another. Note that the resulting database is not meant to be usable with Skype -- see readme')
parser.add_argument('--source-path', type=str, required=True)
parser.add_argument('--target-path', type=str, required=True)
args = parser.parse_args()

# Встроенный Row_factory возвращает ущербный dict без редактирования
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

db_source = sqlite3.connect(args.source_path+'\\main.db')
db_source.row_factory = dict_factory
db_target = sqlite3.connect(args.target_path+'\\main.db')
db_target.row_factory = dict_factory

def post_row(conn, tablename, rec):
    keys = ','.join(rec.keys())
    question_marks = ','.join(list('?'*len(rec)))
    values = tuple(rec.values())
    conn.execute('INSERT INTO '+tablename+' ('+keys+') VALUES ('+question_marks+')', values)


print 'Synchronizing contacts...'
target_contacts = {item['skypename']:item for item in db_target.execute('SELECT * FROM contacts')}
for contact in db_source.execute('SELECT * FROM contacts'):
    if not target_contacts.has_key(contact['skypename']):
        print contact['skypename']
        row = dict()
        for key in ('is_permanent', 'type', 'skypename', 'aliases', 'fullname', 'birthday', 'gender', 'languages',
                    'country', 'province', 'city', 'phone_home', 'phone_office', 'phone_mobile', 'emails',
                    'hashed_emails', 'homepage', 'about', 'avatar_image', 'mood_text', 'rich_mood_text', 'timezone',
                    'displayname', 'given_displayname'):
            row[key] = contact[key]
        post_row(db_target, 'contacts', row)

target_contacts = None


print 'Synchronizing conversations...'
source_convos_by_id = {item['id']:item for item in db_source.execute('SELECT * FROM conversations')}
target_convos = {item['identity']:item for item in db_target.execute('SELECT * FROM conversations')}
for convo in source_convos_by_id.values():
    if not target_convos.has_key(convo['identity']):
        print convo['identity']
        row = dict()
        for key in ('is_permanent', 'identity', 'type', 'is_bookmarked', 'given_displayname', 'displayname',
                    'creator', 'creation_timestamp', 'my_status', 'passwordhint', 'meta_name', 'meta_topic',
                    'meta_guidelines', 'meta_picture', 'guid', 'is_blocked'):
            row[key] = convo[key]
        post_row(db_target, 'conversations', row)

# Rebuild map
target_convos = {item['identity']:item for item in db_target.execute('SELECT * FROM conversations')}


print 'Synchronizing messages...'
added_cnt = 0
checked_cnt = 0
target_messages = {buffer(item['guid']):item for item in db_target.execute('SELECT * FROM messages')}
for message in db_source.execute('SELECT * FROM messages'):
    checked_cnt += 1
    if checked_cnt % 100 == 0:
        sys.stdout.write('.')
    if not target_messages.has_key(buffer(message['guid'])):
        row = dict()
        for key in ('is_permanent', 'chatname', 'author', 'from_dispname', 'guid', 'dialog_partner', 'timestamp', 'type',
                    'sending_status', 'consumption_status', 'edited_by', 'edited_timestamp', 'body_xml', 'identities',
                    'participant_count', 'chatmsg_type', 'chatmsg_status', 'body_is_rawxml', 'crc'):
            row[key] = message[key]
        # Adjust convo id
        convo_id = message['convo_id']
        convo = source_convos_by_id[convo_id]
        convo_identity = convo['identity']
        target_convo = target_convos[convo_identity]
        row['convo_id'] = target_convo['id']
        post_row(db_target, 'messages', row)
        added_cnt += 1
print '\n%d messages added.' % added_cnt


db_target.commit()
db_target.close()