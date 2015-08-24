import argparse
import sqlite3
import codecs
import datetime
import os
import winshell
import re
import SkypeSanityChecks

# Requires winshell, pywin32 (manual download)

parser = argparse.ArgumentParser()
parser.add_argument('-p', '--profile', type=str, required=True, help='Skype profile folder (there could be several for a single windows profile)')
parser.add_argument('--export-conversations', type=str, help='Export direct conversations with my contacts to this folder')
parser.add_argument('--export-rooms', type=str, help='Export chat rooms / group chats to this folder')
parser.add_argument('--add-shortcuts', type=str, help='Add user-friendly shortcut names to the chat rooms and conversations in this folder')
args = parser.parse_args()

conn = sqlite3.connect(args.profile+'\main.db')
conn.row_factory = sqlite3.Row

db_sanity_checks(conn)

# Makes a string suitable to be file name
def neuter_name(name):
    reserved_chars ='\\/:*?"<>|'
    for char in reserved_chars:
        name = name.replace(char, '')
    return name

# Accepts database set of messages and log file name. Exports all messages into that file.
# Returns true if the file was created or rewritten successfully.
def export_log(messages, logname):
    logf = None
    for message in messages:
        if logf is None: # do not create until the first messages to avoid empty files
            logf = codecs.open(logname, 'w', encoding='utf_8_sig')

        timestamp = int(message['timestamp'])
        timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

        type = int(message['type'])
        from_dispname = message['from_dispname']
        body_xml = message['body_xml'] # may be null
        identities = message['identities'] # may be null
        dialog_partner = message['dialog_partner'] # may be null

		# Message types - collected with SELECT DISCTINCT(type) FROM messages at available PCs
		# At this point only Russian messages are available

        if type == 2:
            if body_xml is None:
                log_text = message_texts.
                u'*** %s поменял(а) тему разговора на пустую. ***' % from_dispname # TODO: непроверено, это ли пишет скайп
            else:
                log_text = u'*** %s поменял(а) тему разговора на «%s» ***' % (from_dispname, body_xml) # проверено
        #   4: sent an invintation?
        #   8: unsure what this means but have an example
        elif type == 8:
            log_text = u'*** Пользователь %s теперь может участвовать в этом чате. ***' % (from_dispname)
        #  10:
        elif type == 10:
            log_text = u'*** %s добавил %s к этому чату ***' % (from_dispname, identities) # we should probably convert identities to nicknames
        #  12: you've been deleted
        elif type == 12:
            log_text = u'*** %s удалил %s из чата ***' % (from_dispname, identities) # text not verified by skype
        #  13: <from_dispname> left
        elif type == 13:
            log_text = u'*** %s вышел ***' % from_dispname
        #  30: incoming call?
        #  39: missing call?
        elif (type == 30) or (type == 39):
            log_text = u'*** Пропущенные звонки от %s ***' % from_dispname # TODO: Это не совсем правильно, нужно бы разобраться
        #  50: please add me (body_xml contains message)
        elif type == 50:
            if (body_xml is None) or (body_xml == ''):
                log_text = u'*** %s просит добавить его в ваш список контактов. ***' % from_dispname
            else:
                log_text = u'*** %s просит добавить его в ваш список контактов: %s ***' % (from_dispname, body_xml)
        #  51: sent contact data
        elif type == 51:
            log_text = u'*** %s отправил контактные данные %s ***' % (from_dispname, dialog_partner)
        #  53:
        #  60: %s scraches head
        elif type == 60:
            log_text = from_dispname + body_xml
        #  61: message
        elif type == 61:
            log_text = from_dispname+': '+body_xml
        #  63:
        #  68: sent file (body_xml is enough)
        elif type == 68:
            log_text = from_dispname+': '+body_xml
        # 100: something like "joined the chat"
        # 110: today's birthday
        elif type == 110:
            log_text = u'*** Сегодня день рождения %s ***' % (from_dispname)
        # 201:
        # Others:
        else:
            if body_xml is None:
                log_text = u'%s (неизвестный тип события %d без текста).' % (from_dispname, type)
            else:
                log_text = u'%s (неизвестный тип события %d): %s' % (from_dispname, type, body_xml)

        msg = '['+timestamp_str+'] '+log_text;
        logf.write(msg+'\n')

    result = logf is not None
    if logf is not None:
        logf.close()
    return result

def export_conversations(conn, path, conv_type, link_path):
    convos = conn.execute('SELECT * FROM conversations WHERE type=?', [conv_type])
    for convo in convos:
        cid = convo['id']
        cname = convo['identity']
        print cname

        messages = conn.execute('SELECT * FROM messages WHERE convo_id=? ORDER BY timestamp ASC', [cid])
        log_filename = path+'\\'+neuter_name(cname)+'.log'
        exported = export_log(messages, log_filename)

        if exported and link_path:
            link_filename = link_path+'\\'+neuter_name(convo['displayname'])+'.lnk'
            with winshell.shortcut(link_filename) as link:
                link.path =  os.path.abspath(log_filename) # relative wouldn't do
                link.description = convo['displayname']

# Make sure path exists
def touch_path(path):
	try: 
	    os.makedirs(path)
	except OSError:
	    if not os.path.isdir(path):
	        raise

if args.add_shortcuts:
    touch_path(args.add_shortcuts)

if args.export_conversations:
    print 'Exporting direct conversations...'
    touch_path(args.export_conversations)
    export_conversations(conn, args.export_conversations, 1, args.add_shortcuts)

if args.export_rooms:
    print 'Exporting chat rooms...'
    touch_path(args.export_rooms)
    export_conversations(conn, args.export_rooms, 2, args.add_shortcuts)

