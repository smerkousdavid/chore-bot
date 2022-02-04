import os
import json
import copy
import asyncio
import datetime
try:
    # python2
    import __builtin__
except ImportError:
    # python3
    import builtins as __builtin__

import discord
from discord.ext import tasks
from dotenv import load_dotenv

# load sensitive info
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
CHANNEL = os.getenv('DISCORD_CHANNEL')
ROLE = os.getenv('DISCORD_ROLE')
BOTNAME = os.getenv('DISCORD_BOTNAME')
STORAGE_FILE = 'storage.json'
WEEK_SECONDS = 60*60*24*7

# hack for windows which can't handle some unicode stuff
print = lambda x, *args, **kwargs: __builtin__.print(ascii(x), *args, **kwargs)

# we want those extra perms/events
INTENTS = discord.Intents(
    messages=True,
    guilds=True,
    presences=True,
    reactions=True,
    guild_messages=True,
    guild_reactions=True,
    dm_messages=True,
    dm_reactions=True,
    emojis=True,
    members=True
)

# store chore data
FILE = os.path.abspath(os.path.dirname(__file__))
CHORE_FILE = os.path.join(FILE, 'chores.json')
STORE_FILE = os.path.join(FILE, 'storage.json')
with open(CHORE_FILE, 'r') as fr:
    CHORES = json.load(fr)

# load chore specific stuff
REGULAR_CHORES = CHORES['regular']
ROTATION_CHORES = CHORES['rotation']
ALL_CHORES = REGULAR_CHORES + [None]  # None for rotation


class autosave_dict(dict):
    """ fun little class to auto load and save storage file """
    def __init__(self):
        try:
            with open(STORE_FILE, 'r') as sr:
                update_dict = json.load(sr)
            self.update(update_dict)
        except FileNotFoundError:
            pass

    def __setitem__(self, key, value):
        """ Will automatically save the store state when changed """
        super().__setitem__(key, value)
        with open(STORE_FILE, 'w') as f:
            json.dump(self, f)


# global file saved storage (autosaving enabled)
storage = autosave_dict()


def has_chore_role(user):
    global ROLE
    for r in user.roles:
        if r.name == ROLE:
            return True
    return False


class ChoreBot(discord.Client):
    """ Not thread save and multi-instance safe please only create ONE object and file stuff should be saved outside class """
    async def clear_dms(self, member):
        # removes all messages sent to user
        dms = member.dm_channel
        if dms is None:
            await member.create_dm()
            dms = member.dm_channel

        if dms is not None:
            async for message in dms.history():
                await message.delete()

    async def load_main_message(self):
        if not hasattr(self, '_channel'):
            return
        if not hasattr(self, '_message'):
            self._message = None

        # load previous main message
        message_id = storage.get('message_id', None)
        if self._message is None and message_id is None:
            return
        elif self._message is None:
            print('Attempting to load message from storage')
            try:
                self._message = await self._channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden) as err:
                print('Failed to find main message from id')
                self._message = None

    async def get_completed_ids(self):
        global storage
        if self._message is None:
            return []
        
        # get already completed to make sure dates are valid
        completed = storage.get('completed', {})
        reacted = {}  # to make sure old ones have been deleted on next iter

        # current date
        cdate = datetime.datetime.now().strftime('%A at %I:%M %p')

        # go through all reactions and figure out who has reacted
        for reaction in self._message.reactions:
            async for mem in reaction.users():
                if mem.id in self._member_ids:  # a valid chore member
                    if mem.id in completed:
                        reacted[mem.id] = completed[mem.id]  # use previous date
                    else:
                        reacted[mem.id] = cdate
        
        # iterate through each member's history of dms and get their reactions
        for mem in self._members:
            try:
                dms = mem.dm_channel
                if dms is None:
                    await mem.create_dm()
                    dms = mem.dm_channel

                if dms is None:
                    raise Exception('failed to get dm channel for users')

                messages = await dms.history(limit=10).flatten()
                for message in messages:
                    if message is None:
                        continue
                    
                    # get associated reactions
                    for reaction in message.reactions:
                        async for mem_re in reaction.users():
                            if mem_re.id in self._member_ids:  # make sure it's not bot
                                if mem_re.id in completed:
                                    reacted[mem_re.id] = completed[mem_re.id]  # use previous date
                                else:
                                    reacted[mem_re.id] = cdate
            except Exception as err:
                print(f'Failed to load DMS for user {mem.name} {err}')

        # save the completed list for next time
        storage['completed'] = reacted

        print(f'User ids already reacted\n - {list(reacted.keys())}')

        # now scan original message to fix
        return reacted

    async def clear_and_send(self, member, message):
        # clears the dms and then sends a message
        await self.clear_dms(member)
        return await member.send(message)

    async def update_status(self):
        # not the best solution but it works
        self._message = await self._channel.fetch_message(self._message.id)

        # update the main message
        await self.construct_main_message(force_new=False)

    async def on_raw_reaction_add(self, payload):
        print(f'Reaction added...')
        await self.update_status()

    async def on_raw_reaction_remove(self, payload):
        print(f'Reaction removed...')
        await self.update_status()

    def build_chores(self):
        global storage

        # create the assigned chore list
        self._assigned = {}
        offset = storage.get('offset', 0)  # week offset
        rotation = storage.get('rotation', 0)  # rotation (weekly chore) offset
        rotation_chore = ROTATION_CHORES[rotation % len(ROTATION_CHORES)]

        # iterate through member list and assign chores
        for ind, mem in enumerate(self._members):
            chore_ind = ((ind + offset) % len(ALL_CHORES))
            chore = ALL_CHORES[chore_ind]

            # if chore is none then shift through rotation
            if chore is None:
                chore = rotation_chore

            # invalid chore
            if chore is None:
                print('Could not assign a chore will a null value please check chores.json')
                exit(1)
            
            # set assigned chore
            self._assigned[mem.id] = chore

        # find chores that have not been set
        fix_all = copy.deepcopy(ALL_CHORES)
        fix_all[fix_all.index(None)] = rotation_chore
        self._not_set = len(fix_all) - len(self._assigned.values())
        print('Chores that have not been set', self._not_set)

    async def construct_main_message(self, force_new=False, update_only=False):
        """ Constructs the main channel message """
        is_new = self._message is None or force_new  # purging/posting instead of editing

        if is_new:
            completed = {}  # no one has completed it
        else:
            # get the list by the reactions
            completed = await self.get_completed_ids()
        
        chore_list = []
        compiled = ""
        for ind, mem in enumerate(self._members):
            chore = self._assigned[mem.id]  # get assigned chore
            
            # update assigned list
            chore_list.append(chore)
            is_complete = mem.id in completed

            # add chore number
            compiled += f"{ind + 1} - "

            # add to global announcement
            if not is_complete:
                compiled += f"{mem.name} has **{chore['name']}** duty\n\n"
            else:
                compiled += f"**COMPLETED ({completed[mem.id]})** ~~{mem.name} has **{chore['name']}** duty~~ \n\n"

        # iterate through the assigned chores to say who has what
        compiled += "\n\n**BRIEF CHORE DESCRIPTIONS** (For more detailed instructions, check your DMs)\n*Please react to this message or DMd message when complete*\n```"
        for chore in chore_list:
            compiled += f"{chore['name']}: {chore['short']}\n\n"
        compiled += "```"
  
        # if new then purge and send else just edit the message
        if is_new and not update_only: # call this when we DONT only want to update a message
            print('Checking not done list')
            # if old chores are not done then notify chat
            if hasattr(self, '_message') and self._message is not None:
                completed = storage['completed']
                not_done = set(self._member_ids) - set(completed.keys())
                print(not_done)

                # some have not been finished
                if len(not_done) > 0:
                    members = []
                    for _id in not_done:
                        for mem in self._members:
                            if mem.id == _id:
                                members.append(mem.name)
                                break
                    people = ', '.join(members)
                    not_done_message = f"**NOTE!** The following people did not finish their chores last week: {people}\n\n"
                else:
                    not_done_message = None  # everything is good
            else:
                not_done_message = None   # everything is good

            # delete all previous messages
            await self._channel.purge()

            # send not done list
            if not_done_message is not None:
                n_message = await self._channel.send(not_done_message)
                await n_message.add_reaction('👀')

            # send new chore list
            self._message = await self._channel.send(compiled)
            storage['message_id'] = self._message.id

            # add initial reaction
            await self._message.add_reaction("✅")
        else:
            await self._message.edit(content=compiled)

    async def send_chore_dm(self, mem):
        chore = self._assigned[mem.id]

        # compile message
        message = f"**You have {chore['name']} duty this week.**\n\n Detailed chore requirements:\n```{chore['long']}```\n```Must be completed before 5pm next Monday. React to message when done```"

        # send the message to the users
        message_obj = await self.clear_and_send(mem, message)
        await message_obj.add_reaction("✅")

    async def assign_new_chores(self):
        # main function that shifts offsets and assigns new chores
        global storage

        # before loop starts
        for _ in range(WEEK_SECONDS//10):
            now = datetime.datetime.now()
            if now.hour == 18 and now.date().isoweekday() == 1:  # iso weekday starts at 1 which is monday (default 18 (6pm) on 1 (Monday))
                break
            await asyncio.sleep(30)

        # apply loop
        while True:
            print('Assigning new chores...')
            storage['offset'] = storage.get('offset', 0) + 1
            storage['rotation'] = storage.get('rotation', 0) + 1
            
            # assign the chores to the new users
            self.build_chores()

            # send the new message purge old one
            await self.construct_main_message(force_new=True, update_only=False)

            # send each DM for each chore user
            for mem in self._members:
                await self.send_chore_dm(mem)
            print('Dispatched all messages!')

            # sleep a week
            await asyncio.sleep(WEEK_SECONDS)

    async def on_ready(self):
        """ Once the bot has connected """
        global storage
        try:
            # find the guild and channels by name
            self._guild = discord.utils.find(lambda g: g.name.lower() == GUILD.lower(), client.guilds)
            assert self._guild is not None, f'Could not find guild {GUILD}'
            
            self._channel = discord.utils.find(lambda c: c.name.lower() == CHANNEL.lower(), self._guild.text_channels)
            assert self._channel is not None, f'Could not find channel "{CHANNEL} in guild {GUILD}'
            
            # try to load the previous message if it's still available
            # this is so we modify it instead of purging/posting a new one
            await self.load_main_message()  # if available
            if self._message is not None:
                storage['message_id'] = self._message.id

            print(
                f'Bot connected to guild {GUILD} and channel {CHANNEL}')

            # get all valid chore members (sorted by id)
            self._members = list(sorted(filter(has_chore_role, self._channel.members), key=lambda m: m.id))
            self._member_ids = list(map(lambda m: m.id, self._members))

            # all current available members
            member_names = '\n - '.join([member.name for member in self._members])
            print(f'Chore Members:\n - {member_names}')

            # this is a simple test to check if the same members used in storage
            # are those we want to assign the same chores
            # since we don't want to overcomplicate chore tracking
            # let's just check to see if we're using the same set of members
            old_members = storage.get('members', None)
            if old_members is not None:
                if set(self._member_ids) == set(old_members):  # if they match
                    print('Using the same member list!')
                else:
                    print('Found different member list from last time. Please delete storage.json and try again!')
                    exit(1)
            
            # let's save this check for next time
            storage['members'] = self._member_ids

            # let's build the current chore list
            self.build_chores()

            # if a previous message only update to see if any new checks have been made
            if self._message is not None:
                await self.construct_main_message(update_only=True)

            print('Starting tasks...')
            self.loop.create_task(self.assign_new_chores())
        except AssertionError as err:
            print(f'Error thrown on startup {err}')
            exit(1)

print('Starting chorebot')
client = ChoreBot(intents=INTENTS)
client.run(TOKEN)
