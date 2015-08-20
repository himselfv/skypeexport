import argparse
import sqlite3
import codecs
import datetime
import os
import winshell
import re

# Requires winshell, pywin32 (manual download)

# ОБЩЕЕ
# База данных Skype хранится в AppData/Roaming/Skype/[login]/main.db.
# Она в формате SQLite.
# В ней таблицы:
#   Contacts - все контакты, включая собственный и любые упоминающиеся в чатах.
#   Conversations - по одному на каждый контакт, с которым переписывался + по одному на каждый GroupChat, в котором участвовал.
#   Messages - все сообщения в базе. У каждого указан:
#     conv_id -> conversation, для удостоверения в этом сделан assert_no_convoless_messages()
#     author+from_dispname: кто его написал.
#     timestamp и guid.
#   Всё остальное в messages бывает от случая к случаю:
#     partner_name: отсутствует в любых формах групповой рассылки и ещё иногда.
#     identities: перечисляет адресатов операции, есть не всегда
#     chatname: имя разговора, см. ниже. Есть всегда, но РАЗНОЕ.
# Таким образом для экспорта всех логов достаточно перебрать Conversations и по каждой экспортировать messages в порядке timestamp.

# РАЗГОВОРЫ
# Skype группирует сообщения в разговоры по некоторым своим соображениям. Разговор определяется его ID:
#   #CreatorId/$PartnerId;$ChatUniqueId    для прямых чатов
#   #CreatorId/$ChatUniqueId               для групповых чатов 
#   код:комнаты@thread.skype               для групповых чатов, имеющих уникальный ID такого вида
# Разговор, к которому относится сообщение, указан в chatname.
# Разговоры представляют собой избыточную информацию, они только группируют сообщения. Адресата или комнату сообщения можно однозначно
# восстановить по conv_id.
# По некоторым из разговоров внесены записи с дополнительной информацией в таблицу Chats, но далеко не по всем. Когда в качестве chatname
# указан id группового чата, информацию по нему всегда можно найти в conversations.

# CHATSYNC
# Кроме main.db у Скайпа есть ещё база в собственном формате, называется chatsync. Сложно точно сказать, что в ней есть дополнительно.
# Во всяком случае, там хранятся все версии сообщения, если его редактировали. Возможно так, часть сообщений выгружается туда
# и в main.db отсутствует (есть сообщения об этом, но непроверенные).
# Так или иначе, полезно бы её читать, но это геморрой.
# Ссылки на db-файлы есть в Chats/db_path (и, возможно, conv_dbid).
# То есть, для получения информации из db-файлов есть стратегии:
#  - Перебрать все chats, и загрузить все соотв. db-файлы
#  - Просто загрузить все db-файлы!
#  - Когда нужны версии конкретной записи, посмотреть по ней chatname, и загрузить только этот db-файл.
# Всё это пока оставляю на потом.
# Чтение chatsync: см. также https://github.com/konstantint/skype-chatsync-reader

parser = argparse.ArgumentParser()
parser.add_argument('-p', '--profile', type=str, required=True, help='Skype profile folder (there could be several for a single windows profile)')
parser.add_argument('--export-conversations', type=str, help='Export direct conversations with my contacts to this folder')
parser.add_argument('--export-rooms', type=str, help='Export chat rooms / group chats to this folder')
parser.add_argument('--add-shortcuts', type=str, help='Add user-friendly shortcut names to the chat rooms and conversations in this folder')
args = parser.parse_args()

conn = sqlite3.connect(args.profile+'\main.db')
conn.row_factory = sqlite3.Row

# Приводит строку к виду, годному в качестве имени файла
def neuter_name(name):
    reserved_chars ='\\/:*?"<>|'
    for char in reserved_chars:
        name = name.replace(char, '')
    return name

# Получает список сообщений из базы и название файла лога. Экспортирует все сообщения в указанный файл / обновляет файл
# Возвращает true, если файл по итогам существует (уже был или вновь создан).
def export_log(messages, logname):
    logf = None
    for message in messages:
        if logf is None: # не открываем файл до первого сообщения, а то куча пустых
            logf = codecs.open(logname, 'w', encoding='utf_8_sig')

        timestamp = int(message['timestamp'])
        timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

        from_dispname = message['from_dispname']
        message_type = int(message['type'])
        body_xml = message['body_xml'] # may be null
        identities = message['identities'] # may be null
        dialog_partner = message['dialog_partner'] # may be null

        # Типы сообщений - перечислил все по SELECT DISCTINCT(type) FROM messages на моём компе
        
        #   2: *** <from_dispname> поменял(а) тему разговора на «<body_xml (may be empty)>» ***
        if message_type == 2:
            if body_xml is None:
                log_text = u'*** %s поменял(а) тему разговора на пустую. ***' % from_dispname # TODO: непроверено, это ли пишет скайп
            else:
                log_text = u'*** %s поменял(а) тему разговора на «%s» ***' % (from_dispname, body_xml) # проверено
        #   4: послал приглашение?
        #   8: я хз, что это значит, но пример нашёл
        elif message_type == 8:
            log_text = u'*** Пользователь %s теперь может участвовать в этом чате. ***' % (from_dispname)
        #  10: *** <from_dispname> добавил <identities> к этому чату ***
        elif message_type == 10:
            log_text = u'*** %s добавил %s к этому чату ***' % (from_dispname, identities) # identities надо бы преобразовать
        #  12: вас удалили
        elif message_type == 12:
            log_text = u'*** %s удалил %s из чата ***' % (from_dispname, identities) # текст не сверен со скайпом
        #  13: *** <from_dispname> вышел *** [из этого чата]
        elif message_type == 13:
            log_text = u'*** %s вышел ***' % from_dispname
        #  30: входящий звонок? *** Пропущенные звонки от <from_dispname> *** (также мб что-то ещё, также см. reason - но не всегда)
        #  39: пропущенный звонок? *** Пропущенные звонки от <from_dispname> ***
        elif (message_type == 30) or (message_type == 39):
            log_text = u'*** Пропущенные звонки от %s ***' % from_dispname # TODO: Это не совсем правильно, нужно бы разобраться
        #  50: предложение добавить в список контактов (body_xml содержит сопровождающий текст)
        elif message_type == 50:
            if (body_xml is None) or (body_xml == ''):
                log_text = u'*** %s просит добавить его в ваш список контактов. ***' % from_dispname
            else:
                log_text = u'*** %s просит добавить его в ваш список контактов: %s ***' % (from_dispname, body_xml)
        #  51: отправил контактные данные
        elif message_type == 51:
            log_text = u'*** %s отправил контактные данные %s ***' % (from_dispname, dialog_partner)
        #  53:
        #  60: %s почесал в голове
        elif message_type == 60:
            log_text = from_dispname + body_xml
        #  61: сообщение
        elif message_type == 61:
            log_text = from_dispname+': '+body_xml
        #  63:
        #  68: отправил файл (можно показывать просто body_xml)
        elif message_type == 68:
            log_text = from_dispname+': '+body_xml
        # 100: что-то типа "присоединился к чату"
        # 110: сегодня день рождения
        elif message_type == 110:
            log_text = u'*** Сегодня день рождения %s ***' % (from_dispname)
        # 201:
        else:
            if body_xml is None:
                log_text = u'%s (неизвестный тип события %d без текста).' % (from_dispname, message_type)
            else:
                log_text = u'%s (неизвестный тип события %d): %s' % (from_dispname, message_type, body_xml)

        # Ещё где-то должны быть:
        # send file
        # receive file
        # outgoing call
        # incoming call
        # voicemail

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

def assert_no_convoless_messages(conn):
    orphans = conn.execute('SELECT * FROM messages WHERE convo_id is Null')
    for orphan in orphans:
        raise Exception('Orphan message found - no convo_id!')

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

assert_no_convoless_messages(conn)
