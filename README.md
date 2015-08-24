# skype-export #

Command-line tool to export all Skype conversations as text logs, one file for each Contact and Groupchat. 

Can also merge Skype databases from different PCs (Skype tries to copy all messages everywhere but often fails), generating a union of all your conversations everywhere.

### Requirements ###

* Python 2.7
* pywin32 (separate installer), winshell

### Exporting logs ###

```
skype-export --profile %APPDATA%\Skype\Your_Nickname
--export-conversations SkypeLogs\Contacts
--export-rooms SkypeLogs\GroupChats
--add-shortcuts SkypeLogs
```

`--profile` Path to Skype profile (usually AppData\Roaming\Skype\Your_Nickname)

`--export-conversations` Where to place logs for individual contacts (one on one)

`--export-rooms` Where to place logs for chat rooms / groupchats

`--add-shortcuts` skype-export names logs by contact skype ids (so that you don't get multiple logs with the same content as someone changes their display name). With this, it'll create shortcuts for contact Display names too.

Each time you run the export, it'll recreate and repopulate all affected files, but will keep unrelated files intact.


### Merging databases ###

If you have Skype installed on several PCs, it tries to keep messages synchronized. But this has limitations, and often different PCs have very different conversations. Run this tool on each PC, merging local data into a common database, and then run skype-export on a common database to have all logs from all PCs in one place.

```
skype-merge --source-path %APPDATA%\Skype\Your_Nickname --target-path SkypeLogs\CommonDb
```

Merges all contacts, conversations and messages from a Skype installation at AppData into a single database at SkypeLogs\CommonDb.

`--source-path` Where to take messages from.

`--target-path` Common database to put new messages into.

`--pretend` Do not save anything, just do a test run.

You have to have a target database present before merging anything into it. If you're running merge for the first time, just copy Skype data folder from any PC.

The resulting database is not meant to be used with Skype. It is only sufficient for passing to skype-export.

There's no harm in running merge any number of times. You can keep target database and merge local databases into it e.g. once a month.


### Skype database format ###

For those looking into Skype database format, I've put my findings into [a short cheatsheet](SkypeDb.md). Additional information is available as comments in Python files.