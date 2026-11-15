"""
bot.py  -  Moonlit Quest Bot v2 (Public Version - No Role/Guild Restrictions, No Banners)
=====================================================================================
Moonlit Discord Quest Completer - v2
A Discord bot that automatically completes Discord Quests using your user token.
"""

import asyncio
from dataclasses import dataclass, field
import datetime
import json
import os
import socket
import sys
import time
from typing import Optional

# Force UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import admin_store
import emoji_store
import token_store
from quest_engine import (
    APIError,
    QuestRecord,
    QuestService,
    format_eta,
    make_progress_bar,
)

load_dotenv()

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
PREFIX       = os.getenv("PREFIX", "$")

# BRANDING
BOT_NAME       = "Moonlit Quest v2"
CREDITS        = "</> Quest Bot • Complete. Earn. Conquer."

# COLORS
DARK_COLOR   = 0x2B2D31
ACCENT_COLOR = 0x5865F2
GREEN_COLOR  = 0x57F287
ERROR_COLOR  = 0xED4245
WARN_COLOR   = 0xFEE75C

def E(slot: int) -> str:
    return emoji_store.get(slot)

async def safe_send(target, embed: discord.Embed, view: Optional[discord.ui.View] = None, **kwargs):
    embed.set_image(url=None)
    existing_file = kwargs.pop("file", None)
    existing_files = kwargs.pop("files", [])
    files = []
    if existing_file:
        files.append(existing_file)
    files.extend(existing_files)

    if files:
        if view:
            return await target.send(embed=embed, view=view, files=files, **kwargs)
        return await target.send(embed=embed, files=files, **kwargs)
    if view:
        return await target.send(embed=embed, view=view, **kwargs)
    return await target.send(embed=embed, **kwargs)

async def safe_edit(msg: Optional[discord.Message], embed: discord.Embed, **kwargs):
    if msg is None:
        return
    try:
        embed.set_image(url=None)
        await msg.edit(embed=embed, **kwargs)
    except Exception as e:
        print(f"[safe_edit] Error editing message: {e}")

async def safe_respond(interaction: discord.Interaction, embed: discord.Embed, view: Optional[discord.ui.View] = None, **kwargs):
    embed.set_image(url=None)
    if interaction.response.is_done():
        return await interaction.followup.send(embed=embed, view=view, **kwargs)
    else:
        if view:
            await interaction.response.send_message(embed=embed, view=view, **kwargs)
        else:
            await interaction.response.send_message(embed=embed, **kwargs)
        return await interaction.original_response()

# STATS & REPUTATION STORE
_STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_stats.json")
_user_stats: dict[str, dict] = {}

def _load_stats():
    global _user_stats
    if os.path.exists(_STATS_FILE):
        try:
            with open(_STATS_FILE, "r", encoding="utf-8") as f:
                _user_stats = json.load(f)
        except Exception:
            _user_stats = {}

def _save_stats():
    try:
        with open(_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_stats, f, indent=2)
    except Exception:
        pass

_load_stats()

def get_user_stats(user_id: int) -> dict:
    uid = str(user_id)
    if uid not in _user_stats:
        _user_stats[uid] = {
            "total_completed": 0,
            "total_sessions": 0,
            "total_errors": 0,
            "last_session": None,
        }
        _save_stats()
    return _user_stats[uid]

def bump_stat(user_id: int, **kwargs):
    s = get_user_stats(user_id)
    for k, v in kwargs.items():
        if k == "last_session":
            s[k] = v
        elif isinstance(v, (int, float)) and k in s and isinstance(s[k], (int, float)):
            s[k] += v
        else:
            s[k] = v
    _save_stats()

_autoquest_tasks = {}
_instance_lock_socket = None

def _acquire_instance_lock(port=37492):
    global _instance_lock_socket
    try:
        _instance_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _instance_lock_socket.bind(("127.0.0.1", port))
    except socket.error as e:
        if getattr(e, "errno", None) in (10048, 98):
            print("[FATAL] Another instance of the bot is already running! Exiting.", flush=True)
            sys.exit(1)
        print(f"[InstanceLock] Notice: Could not bind instance lock ({e}). Continuing.", flush=True)

def _is_admin(member):
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return admin_store.is_owner(member.id, guild_owner_id=member.guild.owner_id if member.guild else None)

def _is_bot_owner(user):
    return admin_store.is_owner(user.id)

def _check_channel_allowed(ctx_or_interaction):
    ch_id = admin_store.get_quest_channel()
    if not ch_id:
        return True
    user = ctx_or_interaction.user if hasattr(ctx_or_interaction, "user") else ctx_or_interaction.author
    if _is_admin(user):
        return True
    current_ch = ctx_or_interaction.channel.id
    return current_ch == ch_id

def _embed(title: str, description: str = "", color: int = DARK_COLOR) -> discord.Embed:
    em = discord.Embed(title=title, description=description, color=color)
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _link_embed(user_id: int) -> discord.Embed:
    is_linked = token_store.has_token(user_id)
    status_icon = E(5) if is_linked else E(6)
    status_text = "Linked" if is_linked else "Unlinked"

    em = discord.Embed(title=f"{E(3)} Link Discord Account", color=DARK_COLOR)
    em.description = (
        "*Secure authorization required to initialize core features.*\n\n"
        "**Access Slot:** `MAIN`\n"
        f"**Status:** {status_icon} `{status_text}`\n\n"
        "**How to link:**\n"
        "> Click **Link Account** below and enter your user token.\n"
        f"> {E(17)} **Security Warning:** Never post your account credentials in a public channel or share them with anyone."
    )
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _link_success_embed(username: str, user_id: str) -> discord.Embed:
    em = discord.Embed(title=f"{E(3)} __Account Linked Successfully!__", color=DARK_COLOR)
    em.description = (
        f"Your Discord account **{username}** has been linked.\n"
        f"**Username:** {username}\n"
        f"**User ID:** {user_id}\n\n"
        f"{E(18)} **Next Step:** Use `{PREFIX}questall` to begin completing your quests!"
    )
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _questall_started_embed(display_name: str, queue_pos: int = 1, quest_count: int = 0) -> discord.Embed:
    em = discord.Embed(title=f"{E(1)} Quest Completion Started", color=DARK_COLOR)
    mode_text = f"• **Engine:** {E(13)} Concurrent (~15 Min Finish)"
    if quest_count > 1:
        mode_text += f"\n• **Quests:** Running `{quest_count}` quests in parallel"
    em.description = (
        f"Added to queue for **{display_name}**!\n\n"
        f"{E(3)} **Queue Position:** #{queue_pos}\n"
        f"{mode_text}\n\n"
        f"> Thanks {display_name} Using Moonlit Bot"
    )
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _queue_status_embed(qm) -> discord.Embed:
    running = qm.running_job
    waiting = qm.waiting_jobs
    total_users = qm.total_users()
    total_quests = qm.total_quests_in_queue()

    em = discord.Embed(title=f"{E(3)} Quest Queue • Moonlit", color=DARK_COLOR)
    if running:
        if len(running.quests) > 1:
            active_names = ", ".join(f"`{q.name}`" for q in running.quests_remaining[:3])
            if len(running.quests_remaining) > 3:
                active_names += f" (+{len(running.quests_remaining) - 3} more)"
            quest_line = f"• **Running In Parallel:** {active_names or 'Finishing up...'}"
        else:
            q_name = running.current_quest.name if running.current_quest else (running.quests[0].name if running.quests else "Preparing quest...")
            quest_line = f"• **Current Quest:** `{q_name}`"

        pct = running.current_percent
        em.add_field(
            name=f"{E(1)} Active Solver (Slot #1)",
            value=(
                f"• **User:** <@{running.user_id}> ({running.display_name})\n"
                f"{quest_line}\n"
                f"• **Overall Progress:** `{pct:.1f}%`\n"
                f"• **Active/Remaining Quests:** `{len(running.quests_remaining)}`"
            ),
            inline=False,
        )
    else:
        em.add_field(
            name=f"{E(1)} Active Solver (Slot #1)",
            value=f"*Queue is idle. Run `{PREFIX}questall` to start immediately!*",
            inline=False,
        )

    if waiting:
        lines = []
        for idx, wjob in enumerate(waiting[:10], start=2):
            lines.append(f"**#{idx}** <@{wjob.user_id}> ({wjob.display_name}) — **{len(wjob.quests_remaining)}** quest(s) queued")
        if len(waiting) > 10:
            lines.append(f"*...and {len(waiting) - 10} more user(s) waiting in line*")
        em.add_field(
            name=f"{E(21)} Waiting In Line ({len(waiting)})",
            value="\n".join(lines),
            inline=False,
        )
    else:
        em.add_field(
            name=f"{E(21)} Waiting In Line",
            value="*No other users waiting in queue.*",
            inline=False,
        )

    status_indicator = "🟢 Active & Processing" if running else "⚪ Idle"
    em.add_field(
        name=f"{E(8)} Queue Overview",
        value=(
            f"• **Total Users in Queue:** `{total_users}`\n"
            f"• **Total Pending Quests:** `{total_quests}`\n"
            f"• **Queue Status:** `{status_indicator}`"
        ),
        inline=False,
    )

    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _concurrent_progress_embed(user_id: int, quests_tracker: dict, total_count: int) -> discord.Embed:
    s = get_user_stats(user_id)
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    if total_count == 1 and quests_tracker:
        t = list(quests_tracker.values())[0]
        q = t["quest"]
        pct = t["percent"]
        pv = t.get("progress_val", q.progress_value() if hasattr(q, "progress_value") else 0.0)
        tg = t.get("target_val", q.target if hasattr(q, "target") and q.target else 900.0)
        bar = make_progress_bar(pct, length=10)
        eta_str = format_eta(pv, tg)

        em = discord.Embed(title=f"{E(21)} Quest Progress", color=DARK_COLOR)
        em.description = (
            f"**Progress: {pct:.1f}%**\n"
            f"{bar}\n\n"
            f"{E(3)} **Current Quest:** {q.name}\n"
            f"{E(22)} **Progress Done:** {int(pv)}s / {int(tg)}s\n"
            f"{E(23)} **ETA Time:** {eta_str}\n"
            f"{E(5)} **Quest Done:** {s.get('total_completed', 0)}\n"
            f"{E(24)} **Errors:** {s.get('total_errors', 0)}\n"
            f"{E(25)} **Total Quests:** 1\n\n"
            f"*Last updated: {now_str}*"
        )
        em.set_footer(text=CREDITS)
        em.set_image(url=None)
        return em

    completed = [t for t in quests_tracker.values() if t.get("status") == "completed" or t["quest"].is_done_or_claimable()]
    errors = [t for t in quests_tracker.values() if t.get("status") in ("failed", "error")]
    running = [t for t in quests_tracker.values() if t not in completed and t not in errors]

    comp_count = len(completed)
    err_count = len(errors)
    run_count = len(running)

    pcts = [min(100.0, max(0.0, t.get("percent", 0.0))) for t in quests_tracker.values()]
    avg_pct = (sum(pcts) / max(1, len(pcts))) if pcts else 0.0
    overall_bar = make_progress_bar(avg_pct, length=10)

    running_remaining = [
        max(0.0, t.get("target_val", 900.0) - t.get("progress_val", 0.0))
        for t in running
    ]
    max_rem = max(running_remaining, default=0.0)
    overall_eta = format_eta(0, max_rem) if max_rem > 0 else ("Finishing..." if run_count > 0 else "0s")

    em = discord.Embed(title=f"{E(21)} Concurrent Quest Progress", color=DARK_COLOR)
    lines = [
        f"**Overall Progress: {avg_pct:.1f}%** • {E(13)} Parallel Engine (~15 Min)",
        f"{overall_bar}\n",
        f"{E(23)} **Overall ETA:** `{overall_eta}`",
        f"**Running:** `{run_count}` | **Done:** `{comp_count}` | **Errors:** `{err_count}`\n",
        f"━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for t in quests_tracker.values():
        q = t["quest"]
        pct = min(100.0, max(0.0, t.get("percent", 0.0)))
        pv = t.get("progress_val", 0.0)
        tg = t.get("target_val", 900.0)
        st = t.get("status", "running")

        if st == "completed" or (q.is_done_or_claimable() and pv >= tg and tg > 0):
            icon = "✅"
            st_text = "Done"
            mini_bar = make_progress_bar(100.0, length=8)
            pv_str = f"{int(tg)}s / {int(tg)}s"
        elif st in ("needs_desktop", "desktop_required"):
            icon = "🎮"
            st_text = "Needs PC"
            mini_bar = make_progress_bar(pct, length=8)
            pv_str = f"{int(pv)}s / {int(tg)}s"
        elif st in ("failed", "error"):
            icon = "❌"
            st_text = "Error"
            mini_bar = make_progress_bar(pct, length=8)
            pv_str = f"{int(pv)}s / {int(tg)}s"
        elif st == "stopped":
            icon = "⏹️"
            st_text = "Stopped"
            mini_bar = make_progress_bar(pct, length=8)
            pv_str = f"{int(pv)}s / {int(tg)}s"
        else:
            icon = "⏳"
            st_text = f"{pct:.1f}%"
            mini_bar = make_progress_bar(pct, length=8)
            pv_str = f"{int(pv)}s / {int(tg)}s"

        q_name = q.name
        if len(q_name) > 30:
            q_name = q_name[:28] + ".."
        lines.append(f"{icon} **{q_name}** — `{st_text}`")
        lines.append(f"{mini_bar} `{pv_str}`")

    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"{E(5)} **Done:** {comp_count}/{total_count}  "
        f"{E(24)} **Errors:** {err_count}  "
        f"{E(8)} **All-Time Done:** {s.get('total_completed', 0)}"
    )
    lines.append(f"*Last updated: {now_str}*")

    em.description = "\n".join(lines)
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _help_embed(username: str) -> discord.Embed:
    em = discord.Embed(title="</> Quest Center", color=DARK_COLOR)
    em.description = (
        f"*Welcome back, {username}! Your adventure starts here.*\n"
        f"*Select a menu below to explore quests, rewards, rankings and your progress.*\n\n"
        f"{E(21)} **Quest Board**\n"
        f"Explore & complete available quests»\n\n"
        f"{E(14)} **Rewards**\n"
        f"View your earned rewards & achievements»\n\n"
        f"{E(19)} **Leaderboard**\n"
        f"See who's leading the quest»\n\n"
        f"{E(10)} **My Profile**\n"
        f"Check your progress & statistics»\n\n"
        f"{E(10)} **Quest Info**\n"
        f"Learn how the quest system works»"
    )
    em.set_footer(text=CREDITS)
    em.set_image(url=None)
    return em

def _dm_quest_done_embed(quest: QuestRecord, user_id: int) -> discord.Embed:
    s = get_user_stats(user_id)
    em = discord.Embed(
        title=f"{E(5)} Quest Completed: {quest.name}",
        description=(
            f"**{quest.name}** has been completed successfully! 🎉\n\n"
            f"{E(14)} **Reward:** {quest.reward_name}\n"
            f"{E(8)} **Total Quests Completed:** {s.get('total_completed', 0)}\n\n"
            "Click **Claim Reward** below to claim directly or open Discord Quest Home."
        ),
        color=GREEN_COLOR,
    )
    if quest.image_url:
        em.set_thumbnail(url=quest.image_url)
    em.set_footer(text=CREDITS)
    return em

# VIEWS & MODALS
class TokenModal(discord.ui.Modal, title="Link Your Discord Account"):
    token_input = discord.ui.TextInput(
        label="Discord User Token",
        placeholder="Paste your token here...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=40,
        max_length=150,
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.token_input.value.strip().strip('"').strip("'")
        if raw.count(".") < 2:
            await interaction.response.send_message(
                embed=_embed(f"{E(6)} Invalid Token", "That doesn't look like a valid Discord token. Please try again.", ERROR_COLOR),
                ephemeral=True,
            )
            return

        token_store.set_token(interaction.user.id, raw)
        get_user_stats(interaction.user.id)
        success_em = _link_success_embed(interaction.user.name, str(interaction.user.id))
        await safe_respond(interaction, success_em, ephemeral=True)

class LinkView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Link Your Account", emoji="🔗", style=discord.ButtonStyle.primary, custom_id="v2_link_acc")
    async def link_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TokenModal())

    @discord.ui.button(label="PC Token", emoji="💻", style=discord.ButtonStyle.secondary, custom_id="v2_pc_guide")
    async def pc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guide = (
            "**How to Get Your Token on PC**\n\n"
            "1. Open Discord in your browser at `discord.com/app`\n"
            "2. Press `F12` or `Ctrl+Shift+I` to open Developer Tools\n"
            "3. Click on the **Console** tab\n"
            "4. Paste this code snippet and hit **Enter**:\n"
            "```js\n"
            "(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()\n"
            "```\n"
            "5. Copy the token string (without quotes)\n"
            "6. Click **Link Your Account** and paste it into the popup\n\n"
            "> Never share your token with anyone."
        )
        em = _embed(f"{E(11)} PC Token Guide", guide, WARN_COLOR)
        await safe_respond(interaction, em, ephemeral=True)

    @discord.ui.button(label="Mobile Token", emoji="📱", style=discord.ButtonStyle.secondary, custom_id="v2_mob_guide")
    async def mob_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guide = (
            "**How to Get Your Token on Mobile**\n\n"
            "**Android (Kiwi Browser):**\n"
            "1. Install Kiwi Browser from Google Play Store\n"
            "2. Open `discord.com/app` and log into your account\n"
            "3. Tap menu (3 dots) -> check **Desktop site**\n"
            "4. Tap menu -> **Developer Tools** -> **Console**\n"
            "5. Paste the token script and copy your token\n\n"
            "**iOS:**\n"
            "1. Install Inspect Browser from the App Store\n"
            "2. Log into `discord.com/app` and open Console\n\n"
            "> Never share your token with anyone."
        )
        em = _embed(f"{E(12)} Mobile Token Guide", guide, WARN_COLOR)
        await safe_respond(interaction, em, ephemeral=True)

class ClaimRewardView(discord.ui.View):
    def __init__(self, quest_id: str, quest_name: str):
        super().__init__(timeout=None)
        self.quest_id = quest_id
        self.quest_name = quest_name
        self.add_item(
            discord.ui.Button(
                label="Open Quest Home",
                emoji="🔗",
                url="https://discord.com/quest-home",
                style=discord.ButtonStyle.link,
            )
        )

    @discord.ui.button(label="Claim Reward", emoji="🎁", style=discord.ButtonStyle.success, custom_id="claim_v2_btn")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        token = token_store.get_token(interaction.user.id)
        if not token:
            await interaction.response.send_message("Please link your account with `$link` first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            async with aiohttp.ClientSession() as session:
                svc = QuestService(token, speed_mode="fast")
                res = await svc.claim_reward(session, self.quest_id)

            if isinstance(res, dict) and "code" in res:
                code = res["code"]
                await interaction.followup.send(
                    f"{E(5)} **Reward Claimed!** Your reward code: `{code}`",
                    ephemeral=True,
                )
            elif isinstance(res, dict) and res.get("claimed_at"):
                await interaction.followup.send(
                    f"{E(5)} **{self.quest_name}** reward has been claimed on your Discord account!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"{E(5)} Claim requested! If you don't see it yet, check [Discord Quest Home](https://discord.com/quest-home).",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(
                f"{E(7)} Could not auto-claim (`{e}`). Claim directly at https://discord.com/quest-home",
                ephemeral=True,
            )

class QuestProgressView(discord.ui.View):
    def __init__(self, user_id: int = 0):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(
            discord.ui.Button(
                label="Quest Home",
                emoji="🔗",
                url="https://discord.com/quest-home",
                style=discord.ButtonStyle.link,
            )
        )

    @discord.ui.button(label="Stop Quest", emoji="🛑", style=discord.ButtonStyle.danger, custom_id="v2_stop_quest_btn")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_uid = self.user_id if self.user_id != 0 else interaction.user.id
        if interaction.user.id != target_uid and not _is_admin(interaction.user):
            await interaction.response.send_message("Only the quest owner or an administrator can stop this quest.", ephemeral=True)
            return

        cancelled, pos = await quest_queue.cancel_user(target_uid)
        if target_uid in _autoquest_tasks:
            task = _autoquest_tasks.pop(target_uid, None)
            if task and not task.done():
                task.cancel()
                cancelled = True

        button.disabled = True
        button.label = "Stopped"
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        if cancelled:
            await interaction.followup.send(
                embed=_embed(f"{E(17)} Quest Stopped", "Your active quest process has been stopped.", WARN_COLOR),
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=_embed(f"{E(7)} Nothing Running", "No active quest was found to stop.", WARN_COLOR),
                ephemeral=True
            )

class HelpSelect(discord.ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Quest Center (Home)", description="Back to main overview",            emoji="🏠", value="home"),
            discord.SelectOption(label="Quest Board",          description="Explore & complete available quests",     emoji="📜", value="qboard"),
            discord.SelectOption(label="Rewards",              description="View your earned rewards & achievements", emoji="🎁", value="rewards"),
            discord.SelectOption(label="Leaderboard",          description="See who's leading the quest",             emoji="🪙", value="lb"),
            discord.SelectOption(label="My Profile",           description="Check your progress & statistics",        emoji="🛡️", value="profile"),
            discord.SelectOption(label="Quest Info",           description="Learn how the quest system works",        emoji="ℹ️", value="info"),
        ]
        super().__init__(
            placeholder="Select a menu to explore...",
            min_values=1,
            max_values=1,
            options=opts,
            custom_id="v2_help_menu_select",
        )

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]
        if v == "home":
            em = _help_embed(interaction.user.display_name)
        elif v == "qboard":
            em = _embed(
                f"{E(21)} Quest Board — Commands",
                f"**Available Quest Commands:**\n\n"
                f"`{PREFIX}link` — Link your Discord account to the bot\n"
                f"`{PREFIX}questall` — Complete all quests in parallel (~15 mins)\n"
                f"`{PREFIX}quest [all|#]` — Complete all or specific quest\n"
                f"`{PREFIX}queue` — View real queue status & pending quests\n"
                f"`{PREFIX}stop` — Stop current quest or leave waiting queue\n"
                f"`{PREFIX}stats` — View your quest statistics\n"
                f"`{PREFIX}unlink` — Unlink your account token\n"
                f"`{PREFIX}autoquest` — Background auto-solver\n\n"
                f"**Configuration Commands:**\n"
                f"`{PREFIX}emojis` — View all 25 configurable emoji slots\n"
                f"`{PREFIX}emojichange <slot> <emoji>` — Change emoji\n"
                f"`{PREFIX}emojiapply` — Save and apply emojis to code\n\n"
                f"> *Run `{PREFIX}link` first to connect your account.*",
                DARK_COLOR,
            )
        elif v == "rewards":
            em = _embed(
                f"{E(14)} Rewards & Redemption",
                f"**How to Claim Your Earned Rewards:**\n\n"
                f"• Once any quest reaches 100%, the bot sends you a **DM** with a **Claim Reward** button.\n"
                f"• You can also visit [Discord Quest Home](https://discord.com/quest-home) anytime.\n"
                f"• In-game reward codes can be redeemed directly in your game launcher.\n\n"
                f"> *Run `{PREFIX}questall` to start completing quests!*",
                DARK_COLOR,
            )
        elif v == "lb":
            s = get_user_stats(interaction.user.id)
            em = _embed(
                f"{E(19)} Quest Leaderboard",
                f"**Your Personal Record:**\n\n"
                f"{E(5)} **Quests Completed:** {s.get('total_completed', 0)}\n"
                f"{E(8)} **Total Sessions:** {s.get('total_sessions', 0)}\n"
                f"{E(24)} **Errors:** {s.get('total_errors', 0)}\n\n"
                f"> *Keep completing quests to climb the server ranks!*",
                DARK_COLOR,
            )
        elif v == "profile":
            is_linked = token_store.has_token(interaction.user.id)
            s = get_user_stats(interaction.user.id)
            last_ts = s.get("last_session")
            last_str = f"<t:{int(last_ts)}:R>" if last_ts else "Never"
            em = _embed(
                f"{E(10)} My Profile & Stats",
                f"**User:** <@{interaction.user.id}>\n"
                f"**Linked:** {E(5) if is_linked else E(6)} `{'Yes' if is_linked else 'No'}`\n\n"
                f"{E(5)} **Total Quests Done:** {s.get('total_completed', 0)}\n"
                f"{E(8)} **Total Sessions:** {s.get('total_sessions', 0)}\n"
                f"{E(24)} **Errors:** {s.get('total_errors', 0)}\n"
                f"{E(9)} **Last Active:** {last_str}\n\n"
                f"> *Use `{PREFIX}link` to manage your connected token.*",
                DARK_COLOR,
            )
        else:
            em = _embed(
                f"{E(10)} Quest Info",
                f"**How {BOT_NAME} Works:**\n\n"
                f"1. **Link Token:** Run `{PREFIX}link` and enter your Discord user token securely.\n"
                f"2. **Start Quest:** Run `{PREFIX}questall` to automatically queue and complete all quests.\n"
                f"3. **Track Progress:** Live block progress bars update ETA and completion in real-time.\n"
                f"4. **Claim Rewards:** Claim buttons are sent to your DMs upon completion.\n\n"
                f"> *Your credentials are encrypted and stored safely for quest execution only.*",
                DARK_COLOR,
            )

        em.set_image(url=None)
        try:
            await interaction.response.edit_message(embed=em, view=self.view)
        except Exception:
            await safe_respond(interaction, em, ephemeral=True)

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HelpSelect())

# BOT INITIALIZATION
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or(PREFIX, "="), intents=intents, help_command=None)

# PREFIX COMMANDS
@bot.command(name="link", aliases=["startquest"])
async def link_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    if not _check_channel_allowed(ctx):
        ch_id = admin_store.get_quest_channel()
        await ctx.send(f"⚠️ Quest commands can only be used in <#{ch_id}>.", delete_after=8)
        return
    await safe_send(ctx, _link_embed(ctx.author.id), view=LinkView())

@bot.command(name="unlink")
async def unlink_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    if not token_store.has_token(ctx.author.id):
        await safe_send(ctx, _embed(f"{E(6)} Not Linked", f"You don't have a linked account. Use `{PREFIX}link` to link one.", ERROR_COLOR))
        return
    await quest_queue.cancel_user(ctx.author.id)
    if ctx.author.id in _autoquest_tasks:
        task = _autoquest_tasks.pop(ctx.author.id, None)
        if task and not task.done():
            task.cancel()
    token_store.delete_token(ctx.author.id)
    await safe_send(ctx, _embed(f"{E(5)} Account Unlinked", f"Your token has been removed. Use `{PREFIX}link` to re-link anytime.", GREEN_COLOR))

@bot.command(name="linked")
async def linked_cmd(ctx: commands.Context):
    if not _is_admin(ctx.author):
        await safe_send(ctx, _embed(f"{E(6)} No Permission", "This command is [Admin Only].", ERROR_COLOR))
        return
    user_ids = token_store.get_all_linked_user_ids()
    total = len(user_ids)
    if not user_ids:
        await safe_send(ctx, _embed(f"{E(8)} Linked Users", "No users have linked an account yet.", WARN_COLOR))
        return
    lines = [f"{i+1}. <@{uid}> (`{uid}`)" for i, uid in enumerate(user_ids[:30])]
    extra = f"\n*...and {total - 30} more*" if total > 30 else ""
    em = _embed(f"{E(8)} Linked Users", f"**Total Linked:** {total}\n\n" + "\n".join(lines) + extra, GREEN_COLOR)
    await safe_send(ctx, em)

@bot.command(name="stats")
async def stats_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    is_linked = token_store.has_token(ctx.author.id)
    s = get_user_stats(ctx.author.id)
    last_ts = s.get("last_session")
    last_str = f"<t:{int(last_ts)}:R>" if last_ts else "Never"
    em = _embed(
        f"{E(10)} Quest Statistics - {ctx.author.name}",
        f"**Linked Account:** {E(5) if is_linked else E(6)} `{'Yes' if is_linked else 'No'}`\n"
        f"{E(5)} **Total Quests Completed:** {s.get('total_completed', 0)}\n"
        f"{E(8)} **Total Sessions:** {s.get('total_sessions', 0)}\n"
        f"{E(24)} **Total Errors:** {s.get('total_errors', 0)}\n"
        f"{E(9)} **Last Session:** {last_str}",
        DARK_COLOR,
    )
    await safe_send(ctx, em)

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    await safe_send(ctx, _help_embed(ctx.author.display_name), view=HelpView())

# EMOJI MANAGEMENT
@bot.command(name="emojis", aliases=["emojilist"])
async def emojis_cmd(ctx: commands.Context):
    if not _is_admin(ctx.author):
        await safe_send(ctx, _embed(f"{E(6)} No Permission", "Admin only command.", ERROR_COLOR))
        return

    all_emojis = emoji_store.get_all()
    lines = []
    for slot in sorted(all_emojis.keys()):
        cur = all_emojis[slot]
        lbl = emoji_store.LABELS.get(slot, "Slot")
        lines.append(f"`#{slot:02d}` {cur}  **{lbl}**")

    chunk1 = "\n".join(lines[:13])
    chunk2 = "\n".join(lines[13:])

    em = _embed(
        f"{E(4)} Emoji Slots Configuration",
        f"**Current Emojis (Slots 1–25):**\n\n"
        f"{chunk1}\n{chunk2}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **Change an Emoji:** `{PREFIX}emojichange <slot> <emoji>`\n"
        f"💡 **Apply Changes:** `{PREFIX}emojiapply`\n"
        f"💡 **Reset:** `{PREFIX}emojireset <slot|all>`",
        DARK_COLOR,
    )
    await safe_send(ctx, em)

@bot.command(name="emojichange")
async def emojichange_cmd(ctx: commands.Context, slot: int = None, *, new_emoji: str = None):
    if not _is_admin(ctx.author):
        await safe_send(ctx, _embed(f"{E(6)} No Permission", "Admin only command.", ERROR_COLOR))
        return
    if slot is None or new_emoji is None or slot < 1 or slot > 25:
        await safe_send(ctx, _embed(f"{E(7)} Usage", f"`{PREFIX}emojichange <slot 1-25> <emoji>`", WARN_COLOR))
        return
    new_emoji = new_emoji.strip()
    emoji_store.set_emoji(slot, new_emoji)
    await safe_send(ctx, _embed(f"{E(5)} Emoji Updated", f"Slot #{slot} updated to {new_emoji}. Run `{PREFIX}emojiapply` to apply.", GREEN_COLOR))

@bot.command(name="emojiapply")
async def emojiapply_cmd(ctx: commands.Context):
    if not _is_admin(ctx.author):
        await safe_send(ctx, _embed(f"{E(6)} No Permission", "Admin only command.", ERROR_COLOR))
        return
    emoji_store.apply_to_code()
    await safe_send(ctx, _embed(f"{E(5)} Emojis Applied", "All emoji configurations saved successfully!", GREEN_COLOR))

@bot.command(name="emojireset")
async def emojireset_cmd(ctx: commands.Context, target: str = None):
    if not _is_admin(ctx.author):
        await safe_send(ctx, _embed(f"{E(6)} No Permission", "Admin only command.", ERROR_COLOR))
        return
    if not target:
        await safe_send(ctx, _embed(f"{E(7)} Usage", f"`{PREFIX}emojireset <slot|all>`", WARN_COLOR))
        return
    if target.lower() == "all":
        emoji_store.reset_all()
        await safe_send(ctx, _embed(f"{E(5)} Reset", "All emojis reset to default.", GREEN_COLOR))
        return
    try:
        slot = int(target)
        emoji_store.reset_emoji(slot)
        await safe_send(ctx, _embed(f"{E(5)} Reset", f"Slot #{slot} reset.", GREEN_COLOR))
    except Exception:
        await safe_send(ctx, _embed(f"{E(6)} Error", "Invalid slot number.", ERROR_COLOR))

# REAL QUEST QUEUE MANAGER
@dataclass
class QuestJob:
    user_id: int
    display_name: str
    token: str
    quests: list[QuestRecord]
    mode: str
    msg: Optional[discord.Message] = None
    channel_id: Optional[int] = None
    user_obj: any = None
    created_at: float = field(default_factory=time.time)
    current_quest: Optional[QuestRecord] = None
    current_percent: float = 0.0
    quests_remaining: list[QuestRecord] = field(default_factory=list)
    task: Optional[asyncio.Task] = None
    child_tasks: list[asyncio.Task] = field(default_factory=list)
    cancelled: bool = False

    def __post_init__(self):
        if not self.quests_remaining:
            self.quests_remaining = list(self.quests)
        if not self.child_tasks:
            self.child_tasks = []

class ConcurrentProgressUpdater:
    def __init__(self, msg: Optional[discord.Message], user_id: int, quests: list[QuestRecord], interval: float = 3.5, view: Optional[discord.ui.View] = None):
        self.msg = msg
        self.user_id = user_id
        self.interval = interval
        self.view = view or QuestProgressView(user_id)
        self.trackers: dict[str, dict] = {
            q.id: {
                "quest": q,
                "percent": q.progress_percent(),
                "progress_val": q.progress_value() if hasattr(q, "progress_value") else 0.0,
                "target_val": q.target if hasattr(q, "target") and q.target else 900.0,
                "status": "completed" if q.is_done_or_claimable() else "running",
                "message": "Starting...",
            }
            for q in quests
        }
        self._lock = asyncio.Lock()
        self._dirty = True
        self._stop_event = asyncio.Event()
        self._bg_task: Optional[asyncio.Task] = None

    def start(self):
        if self.msg:
            self._bg_task = asyncio.create_task(self._update_loop())

    async def update_quest(self, quest: QuestRecord, percent: float, status: Optional[str] = None, message: Optional[str] = None):
        async with self._lock:
            if quest.id in self.trackers:
                t = self.trackers[quest.id]
                t["quest"] = quest
                t["percent"] = percent
                t["progress_val"] = quest.progress_value() if hasattr(quest, "progress_value") else 0.0
                t["target_val"] = quest.target if hasattr(quest, "target") and quest.target else 900.0
                if status:
                    t["status"] = status
                if message:
                    t["message"] = message
                self._dirty = True

    async def _update_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.interval)
                if self._stop_event.is_set():
                    break
                async with self._lock:
                    if self._dirty and self.msg:
                        em = _concurrent_progress_embed(self.user_id, self.trackers, len(self.trackers))
                        self._dirty = False
                        await safe_edit(self.msg, em, view=self.view)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ConcurrentProgressUpdater] loop error: {e}")

    async def flush(self):
        async with self._lock:
            if self.msg:
                try:
                    em = _concurrent_progress_embed(self.user_id, self.trackers, len(self.trackers))
                    self._dirty = False
                    await safe_edit(self.msg, em, view=self.view)
                except Exception as ex:
                    print(f"[ConcurrentProgressUpdater] flush error: {ex}")

    async def stop(self):
        self._stop_event.set()
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.view:
            for child in self.view.children:
                if hasattr(child, "disabled") and getattr(child, "style", None) != discord.ButtonStyle.link:
                    child.disabled = True
        await self.flush()

class QuestQueueManager:
    def __init__(self):
        self.running_job: Optional[QuestJob] = None
        self.waiting_jobs: list[QuestJob] = []
        self._lock = asyncio.Lock()

    def get_position(self, user_id: int) -> Optional[int]:
        if self.running_job and self.running_job.user_id == user_id:
            return 1
        for idx, j in enumerate(self.waiting_jobs):
            if j.user_id == user_id:
                return (1 if self.running_job else 0) + idx + 1
        return None

    def next_position(self) -> int:
        if self.running_job is None:
            return 1
        return 1 + len(self.waiting_jobs) + 1

    def is_user_queued(self, user_id: int) -> bool:
        return self.get_position(user_id) is not None

    def total_users(self) -> int:
        return (1 if self.running_job else 0) + len(self.waiting_jobs)

    def total_quests_in_queue(self) -> int:
        total = 0
        if self.running_job:
            total += len(self.running_job.quests_remaining)
        for j in self.waiting_jobs:
            total += len(j.quests_remaining)
        return total

    async def enqueue(self, job: QuestJob) -> int:
        async with self._lock:
            if self.running_job is None:
                self.running_job = job
                pos = 1
                job.task = asyncio.create_task(self._job_worker(job))
                return pos
            else:
                self.waiting_jobs.append(job)
                pos = 1 + len(self.waiting_jobs)
                return pos

    async def cancel_user(self, user_id: int) -> tuple[bool, Optional[int]]:
        async with self._lock:
            if self.running_job and self.running_job.user_id == user_id:
                job = self.running_job
                job.cancelled = True
                if hasattr(job, "child_tasks") and job.child_tasks:
                    for ct in job.child_tasks:
                        if not ct.done():
                            ct.cancel()
                if job.task and not job.task.done():
                    job.task.cancel()
                return True, 1

            for idx, j in enumerate(self.waiting_jobs):
                if j.user_id == user_id:
                    pos = (1 if self.running_job else 0) + idx + 1
                    j.cancelled = True
                    self.waiting_jobs.pop(idx)
                    try:
                        if j.msg:
                            asyncio.create_task(safe_edit(j.msg, _embed(
                                f"{E(17)} Removed From Queue",
                                "Your queued quest request was cancelled.",
                                WARN_COLOR
                            )))
                    except Exception:
                        pass
                    return True, pos
        return False, None

    async def clear_waiting(self) -> int:
        async with self._lock:
            count = len(self.waiting_jobs)
            for j in self.waiting_jobs:
                j.cancelled = True
                try:
                    if j.msg:
                        asyncio.create_task(safe_edit(j.msg, _embed(
                            f"{E(17)} Queue Cleared",
                            "The quest queue was cleared by an administrator.",
                            WARN_COLOR
                        )))
                except Exception:
                    pass
            self.waiting_jobs.clear()
            return count

    async def _advance_next(self):
        async with self._lock:
            if self.waiting_jobs:
                next_job = self.waiting_jobs.pop(0)
                self.running_job = next_job
                next_job.task = asyncio.create_task(self._job_worker(next_job))
            else:
                self.running_job = None

    async def _job_worker(self, job: QuestJob):
        updater: Optional[ConcurrentProgressUpdater] = None
        try:
            bump_stat(job.user_id, total_sessions=1, last_session=datetime.datetime.now().timestamp())
            await asyncio.sleep(1.5)
            if job.cancelled:
                return

            active_quests = [q for q in job.quests if not q.is_done_or_claimable()]
            already_done = [q for q in job.quests if q.is_done_or_claimable()]

            for q in already_done:
                if q.is_completed() or q.is_claimed():
                    bump_stat(job.user_id, total_completed=1)
                    try:
                        dm_view = ClaimRewardView(q.id, q.name)
                        dm_em = _dm_quest_done_embed(q, job.user_id)
                        if job.user_obj:
                            await job.user_obj.send(embed=dm_em, view=dm_view)
                    except Exception:
                        pass

            if not active_quests:
                if job.msg:
                    await safe_edit(job.msg, _embed(
                        f"{E(5)} All Quests Done!",
                        "All your quests are already finished or ready to claim! 🎉",
                        GREEN_COLOR
                    ))
                return

            job.quests_remaining = list(active_quests)
            updater = ConcurrentProgressUpdater(job.msg, job.user_id, job.quests, interval=3.5)
            for q in already_done:
                await updater.update_quest(q, 100.0, status="completed", message="Already done")

            await updater.flush()
            updater.start()

            async with aiohttp.ClientSession() as session:
                svc = QuestService(job.token, speed_mode="fast")

                async def _solve_single(idx: int, q: QuestRecord):
                    if idx > 0:
                        await asyncio.sleep(idx * 1.5)
                    if job.cancelled:
                        return {"status": "stopped", "quest": q}

                    async def _on_q_update(payload):
                        pct = payload.get("percent", 0.0)
                        st = payload.get("status", "running")
                        msg_str = payload.get("message", "")
                        await updater.update_quest(payload["quest"], pct, status=st, message=msg_str)
                        if updater.trackers:
                            job.current_percent = sum(t["percent"] for t in updater.trackers.values()) / len(updater.trackers)

                    try:
                        if not q.is_enrolled():
                            try:
                                await svc.enroll(session, q)
                                await updater.update_quest(q, q.progress_percent(), status="running", message="Enrolled")
                            except APIError as exc:
                                if exc.status not in (400, 403, 404):
                                    raise

                        result = await svc.run_quest(session, q, on_update=_on_q_update)
                        final_q = result.get("quest", q)
                        st = result.get("status")

                        if st == "completed":
                            bump_stat(job.user_id, total_completed=1)
                            await updater.update_quest(final_q, 100.0, status="completed", message="Completed")
                            job.quests_remaining = [rem for rem in job.quests_remaining if rem.id != q.id]
                            try:
                                dm_view = ClaimRewardView(final_q.id, final_q.name)
                                dm_em = _dm_quest_done_embed(final_q, job.user_id)
                                if job.user_obj:
                                    await job.user_obj.send(embed=dm_em, view=dm_view)
                            except Exception as dm_err:
                                print(f"[DM Error:{job.user_id}:{final_q.name}] {dm_err}")
                            return result
                        elif st == "needs_desktop":
                            await updater.update_quest(final_q, final_q.progress_percent(), status="needs_desktop", message="Needs PC/Console")
                            job.quests_remaining = [rem for rem in job.quests_remaining if rem.id != q.id]
                            return result
                        else:
                            bump_stat(job.user_id, total_errors=1)
                            await updater.update_quest(final_q, final_q.progress_percent(), status="failed", message="Failed")
                            job.quests_remaining = [rem for rem in job.quests_remaining if rem.id != q.id]
                            return result
                    except asyncio.CancelledError:
                        await updater.update_quest(q, q.progress_percent(), status="stopped", message="Stopped")
                        raise
                    except Exception as ex:
                        bump_stat(job.user_id, total_errors=1)
                        await updater.update_quest(q, q.progress_percent(), status="failed", message=str(ex))
                        job.quests_remaining = [rem for rem in job.quests_remaining if rem.id != q.id]
                        return {"status": "failed", "quest": q, "reason": str(ex)}

                job.child_tasks = [asyncio.create_task(_solve_single(i, q)) for i, q in enumerate(active_quests)]
                results = await asyncio.gather(*job.child_tasks, return_exceptions=True)

            if updater:
                await updater.stop()

            if not job.cancelled and job.msg:
                s = get_user_stats(job.user_id)
                comp = len([q for q in already_done if q.is_completed() or q.is_claimed()]) + sum(
                    1 for r in results if isinstance(r, dict) and r.get("status") == "completed"
                )
                needs_pc = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "needs_desktop")
                errs = sum(
                    1 for r in results
                    if (isinstance(r, dict) and r.get("status") not in ("completed", "needs_desktop"))
                    or isinstance(r, Exception)
                )
                total = len(job.quests)

                done_view = discord.ui.View(timeout=None)
                done_view.add_item(discord.ui.Button(label="Open Quest Home", emoji="🔗", url="https://discord.com/quest-home", style=discord.ButtonStyle.link))

                if job.mode == "single" and total == 1:
                    if comp > 0:
                        await safe_edit(job.msg, _embed(
                            f"{E(5)} Quest Completed!",
                            f"**{job.quests[0].name}** completed successfully! 🎉",
                            GREEN_COLOR
                        ), view=done_view)
                    elif needs_pc > 0:
                        await safe_edit(job.msg, _embed(
                            f"🎮 Desktop App Required",
                            f"**{job.quests[0].name}** needs PC. Use `{PREFIX}gamehelper` for instructions.",
                            WARN_COLOR
                        ), view=done_view)
                    else:
                        await safe_edit(job.msg, _embed(f"{E(6)} Quest Failed", "Could not complete quest.", ERROR_COLOR), view=done_view)
                else:
                    summary = _embed(
                        f"{E(1)} Quest All — Finished!",
                        f"{E(5)} **Completed:** {comp}/{total}\n"
                        f"{E(6)} **Failed/Errors:** {errs}\n"
                        f"{E(8)} **Total Quests Done (All-Time):** {s.get('total_completed', 0)}",
                        GREEN_COLOR if errs == 0 else WARN_COLOR,
                    )
                    await safe_edit(job.msg, summary, view=done_view)
        except Exception as e:
            print(f"[_job_worker fatal:{job.user_id}] {e}")
        finally:
            job.quests_remaining = []
            job.child_tasks = []
            await self._advance_next()

quest_queue = QuestQueueManager()

# QUEST COMMANDS
@bot.command(name="quest")
async def quest_cmd(ctx: commands.Context, target: str = "all"):
    if admin_store.is_banned(ctx.author.id):
        return
    if not _check_channel_allowed(ctx):
        ch_id = admin_store.get_quest_channel()
        await ctx.send(f"⚠️ Quest commands can only be used in <#{ch_id}>.", delete_after=8)
        return
    token = token_store.get_token(ctx.author.id)
    if not token:
        await safe_send(ctx, _embed(f"{E(6)} Not Linked", f"Please link your account first using `{PREFIX}link`.", ERROR_COLOR))
        return

    pos = quest_queue.get_position(ctx.author.id)
    if pos is not None:
        await safe_send(ctx, _embed(f"{E(7)} Already Active/Queued", f"Position #{pos} in queue.", WARN_COLOR))
        return

    msg = await safe_send(ctx, _embed(f"{E(1)} Fetching Quests...", "Loading quests...", ACCENT_COLOR))
    try:
        async with aiohttp.ClientSession() as session:
            svc = QuestService(token, speed_mode="fast")
            quests = await svc.fetch_quests(session, include_completed=False)
    except Exception as e:
        await safe_edit(msg, _embed(f"{E(6)} Error", f"`{e}`", ERROR_COLOR))
        return

    active = [q for q in quests if q.is_incomplete()]
    if not active:
        await safe_edit(msg, _embed(f"{E(5)} All Quests Done!", "No incomplete quests found.", GREEN_COLOR))
        return

    target_clean = target.strip().lower()
    if target_clean in ("all", "*"):
        chosen_quests = active
        mode = "all"
    else:
        try:
            q_idx = int(target_clean) - 1
            chosen_quests = [active[q_idx]]
            mode = "single"
        except Exception:
            chosen_quests = active
            mode = "all"

    job = QuestJob(
        user_id=ctx.author.id,
        display_name=ctx.author.display_name,
        token=token,
        quests=chosen_quests,
        mode=mode,
        msg=msg,
        channel_id=ctx.channel.id,
        user_obj=ctx.author,
    )
    assigned_pos = await quest_queue.enqueue(job)
    await safe_edit(msg, _questall_started_embed(ctx.author.display_name, queue_pos=assigned_pos, quest_count=len(chosen_quests)), view=QuestProgressView(ctx.author.id))

@bot.command(name="questall")
async def questall_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    if not _check_channel_allowed(ctx):
        ch_id = admin_store.get_quest_channel()
        await ctx.send(f"⚠️ Quest commands can only be used in <#{ch_id}>.", delete_after=8)
        return
    token = token_store.get_token(ctx.author.id)
    if not token:
        await safe_send(ctx, _embed(f"{E(6)} Not Linked", f"Please link your account first using `{PREFIX}link`.", ERROR_COLOR))
        return

    pos = quest_queue.get_position(ctx.author.id)
    if pos is not None:
        await safe_send(ctx, _embed(f"{E(7)} Already Active/Queued", f"Position #{pos} in queue.", WARN_COLOR))
        return

    msg = await safe_send(ctx, _embed(f"{E(1)} Fetching Quests...", "Loading quests...", ACCENT_COLOR))
    try:
        async with aiohttp.ClientSession() as session:
            svc = QuestService(token, speed_mode="fast")
            quests = await svc.fetch_quests(session, include_completed=False)
    except Exception as e:
        await safe_edit(msg, _embed(f"{E(6)} Error", f"`{e}`", ERROR_COLOR))
        return

    active = [q for q in quests if q.is_incomplete()]
    if not active:
        await safe_edit(msg, _embed(f"{E(5)} All Quests Done!", "No incomplete quests found.", GREEN_COLOR))
        return

    job = QuestJob(
        user_id=ctx.author.id,
        display_name=ctx.author.display_name,
        token=token,
        quests=active,
        mode="all",
        msg=msg,
        channel_id=ctx.channel.id,
        user_obj=ctx.author,
    )
    assigned_pos = await quest_queue.enqueue(job)
    await safe_edit(msg, _questall_started_embed(ctx.author.display_name, queue_pos=assigned_pos, quest_count=len(active)), view=QuestProgressView(ctx.author.id))

@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    cancelled, pos = await quest_queue.cancel_user(ctx.author.id)
    auto_task = _autoquest_tasks.pop(ctx.author.id, None)
    if auto_task and not auto_task.done():
        auto_task.cancel()
        cancelled = True

    if cancelled:
        await safe_send(ctx, _embed(f"{E(17)} Quest Stopped", "Your active or queued process has been stopped.", WARN_COLOR))
    else:
        await safe_send(ctx, _embed(f"{E(7)} Nothing Running", "You do not have any active or queued quests.", WARN_COLOR))

@bot.command(name="queue", aliases=["q", "queues"])
async def queue_cmd(ctx: commands.Context):
    if admin_store.is_banned(ctx.author.id):
        return
    if not _check_channel_allowed(ctx):
        ch_id = admin_store.get_quest_channel()
        await ctx.send(f"⚠️ Quest commands can only be used in <#{ch_id}>.", delete_after=8)
        return
    em = _queue_status_embed(quest_queue)
    await safe_send(ctx, em)

@bot.command(name="gamehelper", aliases=["gamescript"])
async def gamehelper_cmd(ctx: commands.Context):
    em = discord.Embed(
        title="🎮 How to Complete Discord Game Quests",
        description=(
            "Discord requires local game detection for `PLAY_ON_DESKTOP` quests.\n\n"
            "### ⚡ Method 1: Discord Desktop Console Script\n"
            "1. Open Discord Desktop App ➔ `Ctrl + Shift + I` ➔ **Console**\n"
            "2. Type `allow pasting` and press Enter\n"
            "3. Visit https://discord.com/quest-home and use the script.\n\n"
            "### 🖥️ Method 2: Dummy Executable\n"
            "Copy `notepad.exe` and rename it to the game executable name, then add it to Discord Settings ➔ **Registered Games**."
        ),
        color=ACCENT_COLOR,
    )
    em.set_footer(text=CREDITS)
    await safe_send(ctx, em)

@bot.command(name="clearqueue", aliases=["qclear"])
async def clear_queue_cmd(ctx: commands.Context):
    if not _is_admin(ctx.author):
        return
    cleared = await quest_queue.clear_waiting()
    await safe_send(ctx, _embed(f"{E(5)} Queue Cleared", f"Cleared **{cleared}** waiting user(s).", GREEN_COLOR))

@bot.command(name="autoquest")
async def autoquest_cmd(ctx: commands.Context, option: str = None):
    if admin_store.is_banned(ctx.author.id):
        return
    token = token_store.get_token(ctx.author.id)
    if not token:
        await safe_send(ctx, _embed(f"{E(6)} Not Linked", f"Please link your account first using `{PREFIX}link`.", ERROR_COLOR))
        return

    uid = ctx.author.id
    is_running = uid in _autoquest_tasks and not _autoquest_tasks[uid].done()
    want_enable = option in ("enable", "on", "start") if option else not is_running

    if not want_enable:
        if is_running:
            _autoquest_tasks[uid].cancel()
            _autoquest_tasks.pop(uid, None)
            await safe_send(ctx, _embed(f"{E(17)} Autoquest Stopped", "Background autoquest disabled.", WARN_COLOR))
        else:
            await safe_send(ctx, _embed(f"{E(7)} Not Active", "Autoquest is not running.", WARN_COLOR))
        return

    if is_running:
        await safe_send(ctx, _embed(f"{E(7)} Already Active", "Autoquest is already running.", WARN_COLOR))
        return

    async def _loop():
        svc = QuestService(token, speed_mode="fast")
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    quests = await svc.fetch_quests(session, include_completed=False)
                    actives = [q for q in quests if q.is_incomplete()]

                if actives and not quest_queue.is_user_queued(uid):
                    job = QuestJob(
                        user_id=uid,
                        display_name=f"Autoquest",
                        token=token,
                        quests=actives,
                        mode="all",
                        msg=None,
                        channel_id=None,
                        user_obj=ctx.author,
                    )
                    await quest_queue.enqueue(job)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[Autoquest:{uid}] {e}")
            await asyncio.sleep(300)

    _autoquest_tasks[uid] = asyncio.create_task(_loop())
    await safe_send(ctx, _embed(f"{E(20)} Autoquest Activated", "Background autoquest service is now active!", GREEN_COLOR))

# OWNER & ADMIN COMMANDS
@bot.command(name="auth")
async def auth_prefix_cmd(ctx: commands.Context, member: discord.Member = None):
    if not _is_bot_owner(ctx.author):
        return
    if member:
        admin_store.authorize_user(member.id)
        await safe_send(ctx, _embed(f"{E(5)} Authorized", f"<@{member.id}> authorized.", GREEN_COLOR))

@bot.command(name="quest-ban")
async def quest_ban_prefix_cmd(ctx: commands.Context, member: discord.Member = None):
    if not _is_bot_owner(ctx.author):
        return
    if member:
        admin_store.ban_user(member.id)
        await quest_queue.cancel_user(member.id)
        await safe_send(ctx, _embed(f"{E(6)} Banned", f"<@{member.id}> banned.", ERROR_COLOR))

@bot.command(name="set-quest-channel")
async def set_quest_channel_prefix_cmd(ctx: commands.Context, channel: discord.TextChannel = None):
    if not _is_bot_owner(ctx.author):
        return
    target_ch = channel or ctx.channel
    admin_store.set_quest_channel(target_ch.id)
    await safe_send(ctx, _embed(f"{E(5)} Channel Set", f"Restricted to <#{target_ch.id}>.", GREEN_COLOR))

# SLASH COMMANDS
@bot.tree.command(name="help", description="View the interactive Quest Center")
async def slash_help(interaction: discord.Interaction):
    await safe_respond(interaction, _help_embed(interaction.user.display_name), view=HelpView())

@bot.tree.command(name="link", description="Link your Discord account token")
async def slash_link(interaction: discord.Interaction):
    await safe_respond(interaction, _link_embed(interaction.user.id), view=LinkView())

@bot.tree.command(name="unlink", description="Unlink your Discord account")
async def slash_unlink(interaction: discord.Interaction):
    token_store.delete_token(interaction.user.id)
    await safe_respond(interaction, _embed(f"{E(5)} Unlinked", "Token removed.", GREEN_COLOR), ephemeral=True)

@bot.tree.command(name="quest", description="Complete Discord quests")
@app_commands.describe(target="Type 'all' or quest number")
async def slash_quest(interaction: discord.Interaction, target: Optional[str] = "all"):
    token = token_store.get_token(interaction.user.id)
    if not token:
        await safe_respond(interaction, _embed(f"{E(6)} Not Linked", "Run `/link` first.", ERROR_COLOR), ephemeral=True)
        return

    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            svc = QuestService(token, speed_mode="fast")
            quests = await svc.fetch_quests(session, include_completed=False)
    except Exception as e:
        await safe_respond(interaction, _embed(f"{E(6)} Error", f"`{e}`", ERROR_COLOR))
        return

    active = [q for q in quests if q.is_incomplete()]
    if not active:
        await safe_respond(interaction, _embed(f"{E(5)} All Quests Done!", "No incomplete quests found.", GREEN_COLOR))
        return

    estimated_pos = quest_queue.next_position()
    msg = await safe_respond(interaction, _questall_started_embed(interaction.user.display_name, queue_pos=estimated_pos, quest_count=len(active)), view=QuestProgressView(interaction.user.id))
    job = QuestJob(
        user_id=interaction.user.id,
        display_name=interaction.user.display_name,
        token=token,
        quests=active,
        mode="all",
        msg=msg,
        channel_id=interaction.channel.id,
        user_obj=interaction.user,
    )
    assigned_pos = await quest_queue.enqueue(job)
    if assigned_pos != estimated_pos:
        await safe_edit(msg, _questall_started_embed(interaction.user.display_name, queue_pos=assigned_pos, quest_count=len(active)), view=QuestProgressView(interaction.user.id))

@bot.tree.command(name="questall", description="Complete all quests in parallel")
async def slash_questall(interaction: discord.Interaction):
    await slash_quest(interaction, target="all")

@bot.tree.command(name="stop", description="Stop your active or queued quest")
async def slash_stop(interaction: discord.Interaction):
    cancelled, pos = await quest_queue.cancel_user(interaction.user.id)
    if cancelled:
        await safe_respond(interaction, _embed(f"{E(17)} Quest Stopped", "Process stopped.", WARN_COLOR))
    else:
        await safe_respond(interaction, _embed(f"{E(7)} Nothing Running", "No active quests found.", WARN_COLOR), ephemeral=True)

@bot.tree.command(name="queue", description="Check active quest queue")
async def slash_queue(interaction: discord.Interaction):
    em = _queue_status_embed(quest_queue)
    await safe_respond(interaction, em)

@bot.tree.command(name="stats", description="View your quest statistics")
async def slash_stats(interaction: discord.Interaction):
    is_linked = token_store.has_token(interaction.user.id)
    s = get_user_stats(interaction.user.id)
    em = _embed(
        f"{E(10)} Quest Statistics - {interaction.user.name}",
        f"**Linked Account:** `{'Yes' if is_linked else 'No'}`\n"
        f"{E(5)} **Total Quests Completed:** {s.get('total_completed', 0)}\n"
        f"{E(8)} **Total Sessions:** {s.get('total_sessions', 0)}",
        DARK_COLOR,
    )
    await safe_respond(interaction, em)

# EVENTS
@bot.event
async def on_ready():
    print(f"[{BOT_NAME}] Online | User: {bot.user}", flush=True)
    bot.add_view(LinkView())
    bot.add_view(HelpView())
    bot.add_view(QuestProgressView(0))
    try:
        synced = await bot.tree.sync()
        print(f"[{BOT_NAME}] Synced {len(synced)} global slash commands", flush=True)
    except Exception as e:
        print(f"Sync error: {e}", flush=True)

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"[Command Error] {ctx.command}: {error}")

if __name__ == "__main__":
    _acquire_instance_lock()
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set in .env!", flush=True)
    else:
        bot.run(BOT_TOKEN)
