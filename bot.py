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

# User subscriptions: {user_id: {stop_id, route_id, frequency_minutes, job_name}}
user_subscriptions: dict[int, dict] = {}

# Bot statistics
bot_stats = {
    "start_time": time.time(),
    "messages_sent": 0,
    "searches_performed": 0,
    "active_subscriptions": 0,
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "🚌 *Welcome to the CityBus Tracker!*\n\n"
        "I can help you track bus arrivals in real-time for CityBus of Greater Lafayette.\n\n"
        "*Commands:*\n"
        "• `/search <stop name>` - Search for a bus stop\n"
        "• `/track` - Start tracking a stop\n"
        "• `/arrivals <stop_id>` - Check arrivals at a stop\n"
        "• `/stop` - Stop receiving notifications\n"
        "• `/status` - Show your active tracking\n\n"
        "Try: `/search Walmart` to get started!",
        parse_mode="Markdown"
    )


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


async def stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle stop selection from inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return ConversationHandler.END
    
    stop_id = data.split(":")[1]
    context.user_data["selected_stop"] = stop_id
    
    # Get routes for this stop
    loader = get_loader()
    stop = loader.get_stop(stop_id)
    routes = get_routes_for_stop(stop_id)
    
    if not routes:
        await query.edit_message_text(
            f"No routes found for this stop.\n"
            "This stop may not be in service."
        )
        return ConversationHandler.END
    
    # Show current arrivals first
    arrivals = get_arrivals_for_stop(stop_id)
    arrivals_text = ""
    if arrivals:
        arrivals_text = "\n\n*Next arrivals:*\n"
        for arr in arrivals[:2]:  # Show only next 2 buses
            route = loader.get_route(arr.route_id)
            route_name = route.route_short_name if route else arr.route_id
            arrivals_text += f"• {format_arrival_message(arr, route_name)}\n"
    
    # Create route selection keyboard
    keyboard = []
    for route in routes:
        name = f"{route.route_short_name}: {route.route_long_name}"
        if len(name) > 45:
            name = name[:42] + "..."
        keyboard.append([InlineKeyboardButton(name, callback_data=f"route:{route.route_id}")])
    
    keyboard.append([InlineKeyboardButton("📍 All Routes", callback_data="route:ALL")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    await query.edit_message_text(
        f"📍 *{stop.stop_name}*{arrivals_text}\n\n"
        "Select a route to track:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECTING_ROUTE


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
        now = datetime.now().strftime("%H:%M")
        lines.append(f"\n_Updated at {now}_")
        
        await context.bot.send_message(
            chat_id=job.chat_id,
            text="\n".join(lines),
            parse_mode="Markdown"
        )
    else:
        await context.bot.send_message(
            chat_id=job.chat_id,
            text=f"📍 {sub['stop_name']}\n\nNo upcoming arrivals at this time.",
        )


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
    
    stop_id = context.args[0].upper()
    loader = get_loader()
    stop = loader.get_stop(stop_id)
    
    if not stop:
        await update.message.reply_text(
            f"Stop '{stop_id}' not found.\n"
            "Use `/search <name>` to find stops.",
            parse_mode="Markdown"
        )
        return
    
    arrivals = get_arrivals_for_stop(stop_id)
    
    if not arrivals:
        await update.message.reply_text(
            f"📍 *{stop.stop_name}*\n\n"
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
    """Handle unknown commands."""
    await update.message.reply_text(
        "❓ Unknown command. Here are the available commands:\n\n"
        "• `/start` - Show welcome message\n"
        "• `/search <stop name>` - Search for a bus stop\n"
        "• `/arrivals <stop_id>` - Check arrivals at a stop\n"
        "• `/status` - Show your active tracking\n"
        "• `/stop` - Stop notifications\n\n"
        "Try `/search Walmart` to get started!",
        parse_mode="Markdown"
    )





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
        BotCommand("search", "Search for a bus stop by name"),
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
        entry_points=[CommandHandler("search", search_command)],
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
    application.add_handler(conv_handler)
    
    # Unknown command handler (must be last)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Start the bot
    print("Starting CityBus Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
