import argparse
import sqlite3
import sys

parser = argparse.ArgumentParser(description='Merges one Skype database into another. Note that the resulting database is not meant to be usable with Skype -- see readme')
parser.add_argument('--source-path', type=str, required=True, help='Local AppData\\Skype path to merge into main repository')
parser.add_argument('--target-path', type=str, required=True, help='Main AppData\\Skype path to merge local one into')
parser.add_argument('--pretend', action='store_true', help='Do not save anything, run the operations dry')
parser.add_argument('--timestamp_leeway', default=120, help='Trigger warning it otherwise matching messages have timestamps differ more than by this number of seconds '
                        +'(see comments in code to understand why timestamps may differ). Usually default settings is good enough.')
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
source_convos = list(db_source.execute('SELECT * FROM conversations'))
target_convos = {item['identity']:item for item in db_target.execute('SELECT * FROM conversations')}
for convo in source_convos:
    if not target_convos.has_key(convo['identity']):
        print convo['identity']
        row = dict()
        for key in ('is_permanent', 'identity', 'type', 'is_bookmarked', 'given_displayname', 'displayname',
                    'creator', 'creation_timestamp', 'my_status', 'passwordhint', 'meta_name', 'meta_topic',
                    'meta_guidelines', 'meta_picture', 'guid', 'is_blocked'):
            row[key] = convo[key]
        post_row(db_target, 'conversations', row)

# Rebuild map source -> target
target_convos = {item['identity']:item for item in db_target.execute('SELECT * FROM conversations')}
convo_id_map = {convo['id']:target_convos[convo['identity']]['id'] for convo in source_convos}


print 'Synchronizing messages...'
# When matching messages, there're only a few things we can rely on:
#   convo_id (adjusted for local pc)
#   body_xml and type
#   remote_id (with various exceptions)
#   timestamp (although it rarely matches exactly, and can at times be sufficiently different)
# So we're going to:
# 1. Load all target messages and build a hashbag out of exact parts for each.
# 2. Load source messages.
# 3. Pass source messages one by one, matching hashbags against targets and then making a best guess based on other properties.

# Messages are grouped into cards by convo:body:type, each card mapping remote_ids => messages
target_messages = {}
target_message_count = 0
sys.stdout.write('Reading')
for message in db_target.execute('SELECT * FROM messages'):
    fingerprint = (message['convo_id'], message['author'], message['body_xml'], message['type'])
    key = message['remote_id']
    # There're a few messages with remote_id = NULL, they break remote_id uniqueness but don't deserve
    # special treatment.
    # So we just substitute ids with some clearly unique ones (no NULL is equal to other NULL).
    if key is None:
        key = 'tnull_'+str(message['id'])

    fp_card = target_messages.get(fingerprint, {}) # existing or new {dict}
    if key in fp_card:
        raise Exception('Duplicate existing convo:body:remote_id triplet')
    fp_card[key] = message # add

    if len(fp_card) == 1:
        target_messages[fingerprint] = fp_card # publish new card
    target_message_count += 1
    if target_message_count % 250 == 0:
        sys.stdout.write('.')
print '\n%d messages initialized in %d fingerprint cards.' % (target_message_count, len(target_messages))


# Then we parse incoming messages one by one, first matching them to a node,
# then to a specific leaf (and noting any possible ambiguity)
checked_cnt = 0
added_cnt = 0
new_fingerprint_cnt = 0 # completely new messages, different convo:body:type
new_remote_id_cnt = 0 # convo:body:type matches some messages but none with the same remote_id
close_calls = [] # new_remote_id + there are some messages with similar timestamp so we are concerned
closest_call = -1

sys.stdout.write('Checking')
for message in db_source.execute('SELECT * FROM messages'):
    convo_id = convo_id_map[message['convo_id']] # localize convo id
    fingerprint = (convo_id, message['author'], message['body_xml'], message['type'])
    key = message['remote_id']
    if key is None:
        key = 'snull_'+str(message['id'])

    # We have to be wary of two scenarios:
    # 1. Same exact message (convo:body:type) with different remote_ids
    # 2. Different messages with same convo:body:type and same remote_id

    is_new = False
    fp_card = target_messages.get(fingerprint)
    if fp_card is None:
        # Not even convo:body:type matches. 100% new
        is_new = True
        new_fingerprint_cnt += 1
    else:
        # Look for matching remote_id
        leaf = fp_card.get(key)
        if leaf is None:
            is_new = True
            new_remote_id_cnt += 1
            # Safety check: does this bucket have messages with similar timestamp? Suspicious. Same message different remote_ids?
            close_call = min([abs(entry['timestamp']-message['timestamp']) for entry in fp_card.values()])
            if (closest_call < 0) or (close_call < closest_call):
                closest_call = close_call
            if close_call < 60:
                close_calls.append(message)
        else:
            is_new = False
            # Safety check, should not fire
            if abs(leaf['timestamp']-message['timestamp']) > args.timestamp_leeway:
                print '\nWARNING: faulty remote_id match, timestamps differ (%d -> %d)' % (message['id'], leaf['id'])

    if is_new:
        row = dict()
        for key in ('is_permanent', 'chatname', 'author', 'from_dispname', 'guid', 'dialog_partner', 'timestamp', 'type',
                    'sending_status', 'consumption_status', 'edited_by', 'edited_timestamp', 'body_xml', 'identities',
                    'participant_count', 'chatmsg_type', 'chatmsg_status', 'body_is_rawxml', 'crc', 'remote_id'):
            row[key] = message[key]
        row['convo_id'] = convo_id
        post_row(db_target, 'messages', row)
        added_cnt += 1

    checked_cnt += 1
    if checked_cnt % 250 == 0:
        sys.stdout.write('.')
print '\n%d messages read, %d messages added.' % (checked_cnt, added_cnt)
print '%d new fingerprints, %d new remote_ids, %d close calls (%d seconds closest)' % (new_fingerprint_cnt, new_remote_id_cnt, len(close_calls), closest_call)
print close_calls


if not args.pretend:
    db_target.commit()
else:
    print 'Saving nothing.'
db_target.close()