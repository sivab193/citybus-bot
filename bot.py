"""
CityBus Telegram Bot
A bot that provides real-time bus arrival notifications for CityBus of Greater Lafayette.
"""

import os
import logging
import time
from datetime import datetime
from typing import Optional

import asyncio
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from gtfs_loader import get_loader, search_stops, get_routes_for_stop, Stop, Route
from realtime import get_next_arrival, get_arrivals_for_stop, format_arrival_message

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Monitoring configuration
ENABLE_HEARTBEAT = os.environ.get("ENABLE_HEARTBEAT", "false").lower() == "true"
HEARTBEAT_URL = os.environ.get("HEARTBEAT_URL", "http://localhost:1903/heartbeat")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "60"))  # seconds

# Conversation states
SELECTING_STOP, SELECTING_ROUTE, SELECTING_FREQUENCY = range(3)

# User subscriptions: {user_id: {stop_id, route_id, frequency_minutes, job_name, message_ids: []}}
user_subscriptions: dict[int, dict] = {}

# Bot statistics
bot_stats = {
    "start_time": time.time(),
    "messages_sent": 0,
    "searches_performed": 0,
    "active_subscriptions": 0,
}

HELP_MESSAGE = (
    "👋 *Welcome to the CityBus Tracker!*\n\n"
    "I can help you track bus arrivals in real-time for CityBus of Greater Lafayette.\n\n"
    "*Commands:*\n"
    "• `/track <stop>` - Track a bus stop (e.g. `/track 205`)\n"
    "• `/schedule <stop> [route] [time]` - Check planned schedule\n"
    "• `/search <name>` - Search for a bus stop\n"
    "• `/arrivals <id>` - Check arrivals at a stop\n"
    "• `/status` - Show your active tracking\n"
    "• `/stop` - Stop receiving notifications\n\n"
    "Try: `/track walmart` or `/track 205`!"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /search command - search for stops and start tracking flow."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a search term.\n"
            "Example: `/search Walmart`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    query = " ".join(context.args)
    stops = search_stops(query, limit=6)
    bot_stats["searches_performed"] += 1
    
    if not stops:
        await update.message.reply_text(
            f"No stops found matching '{query}'.\n"
            "Try a different search term."
        )
        return ConversationHandler.END
    
    # Create inline keyboard with stop options
    keyboard = []
    for stop in stops:
        # Shorten name if too long
        name = stop.stop_name
        if len(name) > 45:
            name = name[:42] + "..."
        keyboard.append([InlineKeyboardButton(name, callback_data=f"stop:{stop.stop_id}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    await update.message.reply_text(
        f"🔍 Found {len(stops)} stops matching '*{query}*':\n"
        "Select a stop to track:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECTING_STOP


async def show_routes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, stop_id: str) -> int:
    """Show route selection menu for a stop."""
    context.user_data["selected_stop"] = stop_id
    loader = get_loader()
    stop = loader.get_stop(stop_id)
    routes = get_routes_for_stop(stop_id)
    
    # Show current arrivals first
    arrivals = get_arrivals_for_stop(stop_id)
    arrivals_text = ""
    if arrivals:
        arrivals_text = "\n\n*Next arrivals:*\n"
        for arr in arrivals[:2]:
            route = loader.get_route(arr.route_id)
            route_name = route.route_short_name if route else arr.route_id
            
            # Format time for display
            time_str = f"{arr.minutes_until} mins"
            abs_time = arr.arrival_time.strftime("%I:%M%p").lstrip("0")
            if arr.minutes_until == 0:
                time_str = f"Now ({abs_time})"
            else:
                time_str = f"{arr.minutes_until}mins ({abs_time})"
                
            arrivals_text += f"• {route_name}: {time_str}\n"

    # Create route selection keyboard
    keyboard = []
    for route in routes:
        name = f"{route.route_short_name}: {route.route_long_name}"
        if len(name) > 45:
            name = name[:42] + "..."
        keyboard.append([InlineKeyboardButton(name, callback_data=f"route:{route.route_id}")])
    
    keyboard.append([InlineKeyboardButton("📍 All Routes", callback_data="route:ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    text = (f"📍 *{stop.stop_name}* ({stop.stop_id}){arrivals_text}\n\n"
            "Select a route to track:")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    return SELECTING_ROUTE


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /track command."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a stop name or code.\n"
            "Example: `/track 205` or `/track walmart`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    query = " ".join(context.args)
    # Use search logic
    loader = get_loader()
    
    # Try exact lookup first
    stop = loader.get_stop(query.upper())
    
    if stop:
        return await show_routes_menu(update, context, stop.stop_id)
        
    # Try search
    results = search_stops(query, limit=5)
    
    if not results:
        await update.message.reply_text(
            f"No stops found matching '{query}'.\n"
            "Try a different search term."
        )
        return ConversationHandler.END
        
    if len(results) == 1:
        # If only one result, go directly to route selection
        return await show_routes_menu(update, context, results[0].stop_id)
    
    # Multiple results - show selection
    keyboard = []
    for stop in results:
        name = stop.stop_name
        if len(name) > 45:
            name = name[:42] + "..."
        keyboard.append([InlineKeyboardButton(name, callback_data=f"stop:{stop.stop_id}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    await update.message.reply_text(
        f"🔍 Found {len(results)} stops matching '*{query}*':\n"
        "Select a stop to track:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECTING_STOP

async def stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle stop selection from inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return ConversationHandler.END
    
    stop_id = data.split(":")[1]
    return await show_routes_menu(update, context, stop_id)


async def route_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle route selection from inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return ConversationHandler.END
    
    route_id = data.split(":")[1]
    context.user_data["selected_route"] = route_id if route_id != "ALL" else None
    
    # Create frequency selection keyboard
    keyboard = [
        [
            InlineKeyboardButton("30s", callback_data="freq:0.5"),
            InlineKeyboardButton("1 min", callback_data="freq:1"),
            InlineKeyboardButton("2 min", callback_data="freq:2"),
        ],
        [
            InlineKeyboardButton("5 min", callback_data="freq:5"),
            InlineKeyboardButton("10 min", callback_data="freq:10"),
            InlineKeyboardButton("15 min", callback_data="freq:15"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    
    loader = get_loader()
    route_name = "All Routes"
    if route_id != "ALL":
        route = loader.get_route(route_id)
        route_name = f"Route {route.route_short_name}" if route else route_id
    
    await query.edit_message_text(
        f"⏰ Tracking *{route_name}*\n\n"
        "How often should I send updates?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECTING_FREQUENCY


async def frequency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle frequency selection and start tracking."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return ConversationHandler.END
    
    frequency_minutes = float(data.split(":")[1])
    stop_id = context.user_data.get("selected_stop")
    route_id = context.user_data.get("selected_route")
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # Stop any existing tracking for this user
    if user_id in user_subscriptions:
        old_job_name = user_subscriptions[user_id].get("job_name")
        if old_job_name:
            jobs = context.job_queue.get_jobs_by_name(old_job_name)
            for job in jobs:
                job.schedule_removal()
    
    # Create a new tracking job
    job_name = f"track_{user_id}_{stop_id}"
    
    # Store subscription
    loader = get_loader()
    stop = loader.get_stop(stop_id)
    route = loader.get_route(route_id) if route_id else None
    
    user_subscriptions[user_id] = {
        "stop_id": stop_id,
        "stop_name": stop.stop_name if stop else stop_id,
        "route_id": route_id,
        "route_name": route.route_short_name if route else "All Routes",
        "frequency_minutes": frequency_minutes,
        "job_name": job_name,
        "chat_id": chat_id,
    }
    
    # Schedule the job
    context.job_queue.run_repeating(
        send_arrival_update,
        interval=frequency_minutes * 60,
        first=5,  # First update after 5 seconds
        name=job_name,
        chat_id=chat_id,
        data={"user_id": user_id},
    )
    
    # Update stats
    bot_stats["active_subscriptions"] = len(user_subscriptions)
    
    route_display = route.route_short_name if route else "All Routes"
    freq_display = f"{int(frequency_minutes * 60)}s" if frequency_minutes < 1 else f"{int(frequency_minutes)} minute(s)"
    await query.edit_message_text(
        f"✅ *Tracking started!*\n\n"
        f"📍 Stop: {stop.stop_name if stop else stop_id}\n"
        f"🚌 Route: {route_display}\n"
        f"⏰ Updates every {freq_display}\n\n"
        "You'll receive your first update shortly.\n"
        "Use `/stop` to stop tracking.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def send_arrival_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a scheduled arrival update to a user."""
    job = context.job
    user_id = job.data["user_id"]
    
    if user_id not in user_subscriptions:
        job.schedule_removal()
        return
    
    sub = user_subscriptions[user_id]
    stop_id = sub["stop_id"]
    route_id = sub.get("route_id")
    
    arrivals = get_arrivals_for_stop(stop_id, route_id)
    
    loader = get_loader()
    
    if arrivals:
        lines = [f"🚏 *{sub['stop_name']}*\n"]
        for arr in arrivals[:2]:  # Show only next 2 buses
            route = loader.get_route(arr.route_id)
            route_name = route.route_short_name if route else arr.route_id
            lines.append(format_arrival_message(arr, route_name))
        
        bot_stats["messages_sent"] += 1
        
        # Add timestamp
        now = datetime.now().strftime("%I:%M %p").lstrip("0")
        lines.append(f"\n_Updated at {now}_")
        
        message = await context.bot.send_message(
            chat_id=job.chat_id,
            text="\n".join(lines),
            parse_mode="Markdown"
        )
        
        # Manage message history (keep last 2)
        if "message_ids" not in sub:
            sub["message_ids"] = []
        
        sub["message_ids"].append(message.message_id)
        
        # Delete old messages if we have more than 2
        while len(sub["message_ids"]) > 2:
            old_msg_id = sub["message_ids"].pop(0)
            try:
                await context.bot.delete_message(chat_id=job.chat_id, message_id=old_msg_id)
            except Exception as e:
                logger.warning(f"Failed to delete message {old_msg_id}: {e}")
                
    else:
        # No arrivals found - send update but keep history clean too
        message = await context.bot.send_message(
            chat_id=job.chat_id,
            text=f"📍 {sub['stop_name']}\n\nNo upcoming arrivals at this time.",
        )
        
        if "message_ids" not in sub:
            sub["message_ids"] = []
        
        sub["message_ids"].append(message.message_id)
        
        while len(sub["message_ids"]) > 2:
            old_msg_id = sub["message_ids"].pop(0)
            try:
                await context.bot.delete_message(chat_id=job.chat_id, message_id=old_msg_id)
            except Exception:
                pass


async def stop_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command - stop tracking."""
    user_id = update.effective_user.id
    
    if user_id not in user_subscriptions:
        await update.message.reply_text("You're not currently tracking any stops.")
        return
    
    sub = user_subscriptions[user_id]
    job_name = sub.get("job_name")
    
    if job_name:
        jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in jobs:
            job.schedule_removal()
    
    # Cleanup messages: Keep only the LAST message, delete others
    if "message_ids" in sub:
        # Remove all except the last one
        while len(sub["message_ids"]) > 1:
            old_msg_id = sub["message_ids"].pop(0)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=old_msg_id)
            except Exception:
                pass
    
    del user_subscriptions[user_id]
    bot_stats["active_subscriptions"] = len(user_subscriptions)
    
    await update.message.reply_text(
        "✅ Tracking stopped.\n\n"
        "Use `/search <stop name>` to start tracking again.",
        parse_mode="Markdown"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show current tracking status."""
    user_id = update.effective_user.id
    
    if user_id not in user_subscriptions:
        await update.message.reply_text(
            "You're not currently tracking any stops.\n"
            "Use `/search <stop name>` to start.",
            parse_mode="Markdown"
        )
        return
    
    sub = user_subscriptions[user_id]
    await update.message.reply_text(
        f"📊 *Current Tracking:*\n\n"
        f"📍 Stop: {sub['stop_name']}\n"
        f"🚌 Route: {sub['route_name']}\n"
        f"⏰ Updates every {sub['frequency_minutes']} minute(s)\n\n"
        "Use `/stop` to stop tracking.",
        parse_mode="Markdown"
    )


async def arrivals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /arrivals command - check arrivals at a stop."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a stop ID.\n"
            "Example: `/arrivals BUS215`\n\n"
            "Use `/search <name>` to find stop IDs.",
            parse_mode="Markdown"
        )
        return
    
    search_term = context.args[0]
    
    # Try exact lookup first
    loader = get_loader()
    stop = loader.get_stop(search_term.upper())
    
    # If not found, try searching
    if not stop:
        search_results = search_stops(search_term, limit=1)
        if search_results:
            stop = search_results[0]
        else:
            await update.message.reply_text(
                f"Stop '{search_term}' not found.\n"
                "Use `/search <name>` to find stops.",
                parse_mode="Markdown"
            )
            return
    
    stop_id = stop.stop_id
    arrivals = get_arrivals_for_stop(stop_id)
    
    if not arrivals:
        await update.message.reply_text(
            f"📍 *{stop.stop_name}* ({stop.stop_id})\n\n"
            "No upcoming arrivals at this time.",
            parse_mode="Markdown"
        )
        return
    
    lines = [f"📍 *{stop.stop_name}*\n"]
    for arr in arrivals[:2]:  # Show only next 2 buses
        route = loader.get_route(arr.route_id)
        route_name = route.route_short_name if route else arr.route_id
        lines.append(format_arrival_message(arr, route_name))
    
    now = datetime.now().strftime("%H:%M")
    lines.append(f"\n_Updated at {now}_")
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel in conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Cancelled.")
    else:
        await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown messages or commands."""
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")





async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /schedule command."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a stop.\n"
            "Usage: `/schedule <stop> [route] [duration]`\n"
            "Example: `/schedule 205 21 2hrs`",
            parse_mode="Markdown"
        )
        return

    # Parse args
    # Strategy: 
    # 1. First arg group is STOP (could be "walmart", "205", "north walmart")
    # 2. Last arg could be DURATION ("2hrs", "30m")
    # 3. Middle arg could be ROUTE ("21", "4B")
    
    args = list(context.args)
    duration_min = None
    route_filter = None
    
    # Check for duration at end
    if args[-1].lower().endswith(("hrs", "hr", "h", "mins", "min", "m")):
        dur_str = args.pop().lower()
        try:
            if "h" in dur_str:
                duration_min = float(dur_str.split("h")[0]) * 60
            elif "m" in dur_str:
                duration_min = float(dur_str.split("m")[0])
        except ValueError:
            pass
            
    # Routes are usually short: "1A", "23", "4", "Silver"
    # Allow routes with letters that aren't duration keywords
    possible_route = args[-1].upper()
    is_route = False
    
    # Heuristic: Short (<=6 chars) and not a duration string
    if len(possible_route) <= 6 and not possible_route.endswith(('HRS', 'MINS', 'HR', 'MIN', 'H', 'M')):
         # It's likely a route if it has digits OR is a known route name
         # For now, simplistic check: assume it is a route if we successfully parsed duration from the *previous* token? 
         # No, route is before duration.
         
         # If we didn't pop duration, this might be route.
         # Logic: If it looks like a route (digits) or is short.
         if any(c.isdigit() for c in possible_route) or possible_route in ["SILVER", "GOLD", "BLACK", "BRONZE"]:
             is_route = True
             
    if is_route:
        route_filter = args.pop().upper()
        
    # Remaining is stop query
    query = " ".join(args)
    if not query:
         await update.message.reply_text("Please provide a stop name.")
         return
         
    loader = get_loader()
    
    # Resolve stop
    stop = loader.get_stop(query.upper())
    if not stop:
        search_results = search_stops(query, limit=1)
        if search_results:
            stop = search_results[0]
        else:
            await update.message.reply_text(f"Stop '{query}' not found.")
            return

    # Calculate time
    now = datetime.now()
    day_name = now.strftime("%A").lower()
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    
    # Grace period: Show buses from 15 mins ago
    query_seconds = max(0, current_seconds - 900)
    
    # Use rest of day if duration not specified
    duration_seconds = int(duration_min * 60) if duration_min else None
    
    scheduled = loader.get_scheduled_arrivals(
        stop.stop_id, 
        day_name, 
        query_seconds, 
        duration_seconds
    )
    
    # Filter by route if specified
    if route_filter:
        scheduled = [s for s in scheduled if s["route_id"] == route_filter]
        
    if not scheduled:
        msg = f"📅 *{stop.stop_name}* ({stop.stop_id})\n"
        msg += f"Route: {route_filter if route_filter else 'All'}\n\n"
        msg += "No buses scheduled for the rest of the day."
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
        
    msg = f"📅 *{stop.stop_name}* ({stop.stop_id})\n"
    if route_filter:
        msg += f"Route: {route_filter}\n"
    if duration_min:
        msg += f"Next {int(duration_min)} mins:\n\n"
    else:
        msg += f"Rest of {day_name.capitalize()}:\n\n"
        
    for s in scheduled[:15]: # Limit to avoid huge messages
        t = s["time_seconds"]
        
        # Determine if past or future
        status_icon = "✅" 
        if t < current_seconds:
            status_icon = "⏮️" # Past
            
        # Normalize > 24h
        h = t // 3600
        m = (t % 3600) // 60
        
        day_suffix = ""
        if h >= 24:
            h -= 24
            day_suffix = " (+1)"
            
        ampm = "AM" if h < 12 else "PM"
        h_disp = h if 1 <= h <= 12 else h - 12
        if h_disp == 0: h_disp = 12
        
        time_str = f"{h_disp}:{m:02d}{ampm}{day_suffix}"
        
        route = loader.get_route(s["route_id"])
        r_name = route.route_short_name if route else s["route_id"]
        
        msg += f"{status_icon} *{time_str}* - {r_name} to {s['headsign']}\n"
        
    if len(scheduled) > 15:
        msg += f"\n...and {len(scheduled) - 15} more."
        
    await update.message.reply_text(msg, parse_mode="Markdown")


async def send_heartbeat_loop():
    """Periodically send heartbeat to monitoring dashboard."""
    await asyncio.sleep(10)  # Wait for bot to fully start
    
    while True:
        try:
            # Check Telegram API health
            telegram_health = "unknown"
            try:
                # Try a quick API call
                bot_info = await application.bot.get_me()
                telegram_health = "healthy"
            except Exception as e:
                telegram_health = f"unhealthy: {str(e)[:50]}"
            
            # Check GTFS-RT feed health
            gtfs_health = "unknown"
            try:
                from realtime import fetch_trip_updates
                feed = fetch_trip_updates()
                gtfs_health = "healthy" if len(feed.entity) > 0 else "no data"
            except Exception as e:
                gtfs_health = f"unhealthy: {str(e)[:50]}"
            
            # Prepare heartbeat payload
            payload = {
                "service": "CityBus Lafayette Telegram Bot",
                "bot_id": "citybus-lafayette",
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": int(time.time() - bot_stats["start_time"]),
                "telegram_api_health": telegram_health,
                "gtfs_rt_health": gtfs_health,
                "stats": {
                    "active_subscriptions": bot_stats["active_subscriptions"],
                    "total_messages_sent": bot_stats["messages_sent"],
                    "total_searches": bot_stats["searches_performed"],
                }
            }
            
            # Send to dashboard
            response = requests.post(
                HEARTBEAT_URL,
                json=payload,
                timeout=5,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                logger.info(f"Heartbeat sent successfully to {HEARTBEAT_URL}")
            else:
                logger.warning(f"Heartbeat failed: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Heartbeat connection error: {e}")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        
        # Wait before next heartbeat
        await asyncio.sleep(HEARTBEAT_INTERVAL)


# Global reference for heartbeat task
application = None

async def post_init(app: Application):
    """Initialize heartbeat after bot starts."""
    global application
    application = app
    
    # Set bot commands for autocomplete
    commands = [
        BotCommand("start", "Show welcome message and help"),
        BotCommand("track", "Track a bus stop"),
        BotCommand("schedule", "Check planned schedule"),
        BotCommand("arrivals", "Check arrivals at a specific stop"),
        BotCommand("status", "Show your active tracking status"),
        BotCommand("stop", "Stop receiving notifications"),
    ]
    await app.bot.set_my_commands(commands)
    print("Bot commands registered for autocomplete")
    
    # Start heartbeat monitoring only if enabled
    if ENABLE_HEARTBEAT:
        print(f"Heartbeat monitoring enabled")
        print(f"  URL: {HEARTBEAT_URL}")
        print(f"  Interval: {HEARTBEAT_INTERVAL}s")
        asyncio.create_task(send_heartbeat_loop())
    else:
        print("Heartbeat monitoring disabled (set ENABLE_HEARTBEAT=true to enable)")


def main():
    """Run the bot."""
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        print("\nTo run the bot:")
        print("  1. Create a bot with @BotFather on Telegram")
        print("  2. Set the token: export TELEGRAM_BOT_TOKEN='your_token_here'")
        print("  3. Run again: python3 bot.py")
        return
    
    # Pre-load GTFS data
    print("Loading GTFS data...")
    loader = get_loader()
    print(f"Loaded {len(loader.stops)} stops and {len(loader.routes)} routes")
    
    # Create application with post_init callback
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Create conversation handler for search/track flow
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_command),
            CommandHandler("track", track_command),
        ],
        states={
            SELECTING_STOP: [CallbackQueryHandler(stop_selected)],
            SELECTING_ROUTE: [CallbackQueryHandler(route_selected)],
            SELECTING_FREQUENCY: [CallbackQueryHandler(frequency_selected)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_tracking))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("arrivals", arrivals_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(conv_handler)
    
    # Unknown message handler (must be last)
    application.add_handler(MessageHandler(filters.ALL, unknown_command))
    
    # Start the bot
    print("Starting CityBus Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
