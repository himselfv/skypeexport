# Overview #
Skype database is kept in AppData\Roaming\Skype\[login]\main.db. It's in SQLite format.

Main tables:

 * `Contacts` - all contacts, including your own and any referenced in chats.
 * `Conversations` - one for each contact you talked to + one for each groupchat you participated in.
 * `Messages` - all messages and events

# Messages #
Each entry in Messages has at least these fields:

 * `convo_id` -> conversation
 * `author`+`from_dispname` - who wrote this
 * `timestamp`
 * `type` (event type) + `body_xml`

The rest of the fields are occasional:
 
 * `partner_name` - missing in any group messages and sometimes else
 * `identities` - lists event recipients, often missing
 * `chatname` - always present but means different things, see below

Therefore to export all logs it's enough to go through Conversations and export messages for each in Timestamp order.

# Chats #
Skype groups messages into chats by some internal rules. Chats exist primarily as IDs in messages.chatname field:
   #CreatorId/$PartnerId;$ChatUniqueId    for direct chats
   #CreatorId/$ChatUniqueId               for chat rooms / groupchats
   19:roomcode@thread.skype               for newer chat rooms
There can be multiple chats for one contact, but only one chat for each chat room.
Chats are redundant, they only group messages. Dialogue partner or room can be clearly identified from conv_id.
Some chats have corresponding entries in Chats table, but not all. When chatname is a groupchat id, groupchat is available in Conversations table.

# Chatsync #
Besides main.db Skype also has another DB in propietary format called chatsync. It's hard to tell what additional info goes there.

At the very least it hosts all versions of the message if it was edited. It's also possible some messages are archived to chatsync and deleted from main.db (by unconfirmed reports).

At any rate it'd be nice to read it but it's a pain.

See: https://github.com/konstantint/skype-chatsync-reader