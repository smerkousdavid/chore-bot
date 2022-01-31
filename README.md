# chore-bot
Simple discord bot to manage chores for our house

## Requirements
This repo is mainly for me an my housemates so I expect you should know how to create a discord bot already.
If not please google it as there are step-by-step guides online.

## Environments file
The environment file .env (expected to be in the same location as the script)
should have the following keys
```
DISCORD_TOKEN=<bot API token>
DISCORD_GUILD=<name of discord server synonymous to guild name>
DISCORD_CHANNEL=<name of channel where to assign random chores to>
DISCORD_ROLE=<name of the role of people who can be assigned chores>
DISCORD_BOTNAME=<name of the bot>
```

## Chores file
Please see chores.json to modify the list of chores you wish to assign to people with the Chores role 

## Installation
Installation is simple
```bash
git clone https://github.com/smerkousdavid/chore-bot
cd chore-bot
python -m pip install -r requirements.txt
python bot.py
```
