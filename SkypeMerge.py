import argparse
import sqlite3
import sys

'''
WARNING:
1. You have to have a target database beforehand. Copy main.db from any of the PCs.
2. The resulting database is NOT meant to be usable with Skype. Not all fields and not all tables are synchronized,
 it's only good enough to work for skype-export to produce your combined logs.
3. All databases must be for the same skype user. This tool will not merge databases of different users.
'''

parser = argparse.ArgumentParser(description='Merges one Skype database into another. Note that the resulting database is not meant to be usable with Skype -- see comments in code')
parser.add_argument('--source-path', type=str, required=True, help='Local AppData\\Skype path to merge into main repository')
parser.add_argument('--target-path', type=str, required=True, help='Main AppData\\Skype path to merge local one into')
parser.add_argument('--pretend', action='store_true', help='Do not save anything, run the operations dry')
parser.add_argument('--timestamp_leeway', default=120, help='Trigger warning it otherwise matching messages have timestamps differ more than by this number of seconds '
                        +'(see comments in code to understand why timestamps may differ). Usually default settings is good enough.')
args = parser.parse_args()

# sqlite3.row_factory gives read-only dict
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



'''
Sync is trivial, just match skypename. We assume these cannot change (otherwise it's undoable anyway).
'''

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



'''
Convo sync is trivial again, match identity. For contacts it's a skypename, so invariant.
There's a slight chance some groupchats might be duplicated, the same groupchat sometimes gets different IDs at different PCs
($Source/$Target;$Id, 19:code@skype.thread). At this point nothing can be done about it.
'''

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



'''
Matching messages is non-trivial, there's no single 'unique_id' field to check. We have to half-match, half-guess.
Good news is the results are more or less certain nevertheless.

Fields we SHOULD rely on. These fields are the core of the message, if any changes it's 100% a completely different message (spare for message editing which we'll cover later).
  convo_id
  author
  body_xml
  type

Yet there can legally be messages in the same conversation, by the same author, with the same content.

Fields we can consult to further distinguish them:

  timestamp:
    A bit off between PCs due to clock discrepancy (tens of seconds). Further off when one side had misconfigured time zone (hours).
    Even further off when one side had wrong time (month, years, anything).

  remote_id:
    Appears to be a `messages.id` at a recipient PC, or a relay PC, whoever receives the message first. In most cases, once set, this will not change
    and will travel with the message wherever it goes.
    It is not unique by itself:
    - Comes from different PCs (sometimes one relay, sometimes another, with different ids)
    - Recipient/relay may reinstall Skype, restarting the ids.
    - There ARE duplicate remote_ids, even for the same convo.
    It is also not quite invariant between PCs:
    - Some rare message types skip remote_id sync (e.g. some authorization requests get remote_id == local messages.id on both sides)
    - Rarely messages have it as NULL (again, often authorization requests)
    - Rarely messages come in pairs, having same convo:body:remote_id but different types (e.g. 30:39).

    Therefore we cannot quite rely on it alone. But it works very well to distinguish between otherwise similar messages, because
    it's improbable that both rare events happen at once.

Fields we CANNOT rely on for matching:
  id: database-local
  guid: despite the potential, database-local
  crc: reflects message content, but not 100% reliable. Constant for some types of messages, for messages < 2-4 chars, often same body_xml gives different crc.
       Better just check body_xml.
  dialog_partner,
  participant_count: messages are grouped into conversations differently on different PCs

The strategy is:
1. Match message by its fingerprint (convo:author:body:type).
2. If there are several matches, select one with matching remote_id.
3. If no remote_id matches, assume new message but run safety checks on timestamp (are there suspiciously well timed messages?)
'''

print 'Synchronizing messages...'
# Messages are grouped into cards by fingerprint, each card mapping remote_ids => messages
target_messages = {}
target_message_count = 0
sys.stdout.write('Reading')
for message in db_target.execute('SELECT * FROM messages'):
    fingerprint = (message['convo_id'], message['author'], message['body_xml'], message['type'])
    key = message['remote_id']
    # There're a few messages with remote_id = NULL, they break remote_id uniqueness. We could map
    # remote_ids to arrays but that's too costly for just a few cases.
    # Substitute NULLs with some unique ids, but same ones each time (or we'll add NULL entries again and again)
    if key is None:
        key = message['id'] # local id, why not

    fp_card = target_messages.get(fingerprint, {}) # existing or new {dict}
    if key in fp_card:
        raise Exception('Duplicate existing fingerprint:remote_id')
    fp_card[key] = message # add

    if len(fp_card) == 1:
        target_messages[fingerprint] = fp_card # publish new card
    target_message_count += 1
    if target_message_count % 250 == 0:
        sys.stdout.write('.')
print '\n%d messages initialized in %d cards.' % (target_message_count, len(target_messages))


# Then we parse incoming messages one by one, first matching them to a node, then to a specific leaf (noting any possible ambiguity)
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
        key = message['id']

    # Figure if this is a new message
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
        if message['remote_id'] is None:
            row['remote_id'] = message['id'] # use local id if remote_id is not set
        post_row(db_target, 'messages', row)
        added_cnt += 1

    checked_cnt += 1
    if checked_cnt % 250 == 0:
        sys.stdout.write('.')
print '\n%d messages read, %d messages added.' % (checked_cnt, added_cnt)
print '%d new fingerprints, %d new remote_ids, %d close calls (%d seconds closest)' % (new_fingerprint_cnt, new_remote_id_cnt, len(close_calls), closest_call)


if not args.pretend:
    db_target.commit()
else:
    print 'Saving nothing.'
db_target.close()