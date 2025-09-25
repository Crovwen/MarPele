import logging
import random
import asyncio
from io import BytesIO
from typing import Dict, List, Tuple

import os
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler

# تنظیمات
TOKEN = os.getenv('BOT_TOKEN')
BOARD_IMAGE = 'board.jpg'
EMOJIS = ['🦋', '🐙', '🐸', '🍄']
CELL_SIZE = 55
BOARD_SIZE = 550
FONT_PATH = 'NotoColorEmoji.ttf'

# نقشه مارپله
SNAKES_LADDERS = {
    # نردبون‌ها
    5: 27, 9: 51, 22: 60, 28: 54, 44: 79, 53: 69, 66: 88, 71: 92, 85: 97,
    # مارها
    13: 7, 37: 19, 80: 43, 86: 46, 91: 49, 99: 4
}

# States
SELECT_MODE, SELECT_LEVEL, SELECT_EMOJI, PLAYING = range(4)

# State بازی‌ها
games: Dict[int, Dict] = {}

# تابع محاسبه موقعیت
def get_position(n: int) -> Tuple[int, int]:
    if n == 0:
        return 27, 522
    row = 9 - (n - 1) // 10
    col = (n - 1) % 10
    if row % 2 == 1:
        col = 9 - col
    x = col * CELL_SIZE + 27
    y = row * CELL_SIZE + 27
    return x, y

# تابع ویرایش عکس
def update_board_image(positions: Dict[str, int], emojis: Dict[str, str]) -> BytesIO:
    img = Image.open(BOARD_IMAGE).convert('RGBA')
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 40)
    
    for user_id, pos in positions.items():
        if pos > 0:
            emoji = emojis[user_id]
            x, y = get_position(pos)
            draw.text((x - 20, y - 20), emoji, font=font, fill=(255, 255, 255, 255))
    
    bio = BytesIO()
    bio.name = 'updated_board.jpg'
    img.save(bio, 'JPEG')
    bio.seek(0)
    return bio

# شروع بازی
async def start_marple(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_chat.type not in ['supergroup', 'group']:
        await update.message.reply_text('این بازی فقط در گروه‌ها کار می‌کنه!')
        return ConversationHandler.END
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    games[chat_id] = {
        'initiator': user_id,
        'players': [user_id],
        'positions': {str(user_id): 0},
        'emojis': {str(user_id): None},
        'current_player': 0,
        'mode': None,
        'level': None,
        'message_id': None,
        'selected_emojis': {}
    }
    
    keyboard = [
        [InlineKeyboardButton("۲ نفره", callback_data='mode_2')],
        [InlineKeyboardButton("۴ نفره", callback_data='mode_4')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await update.message.reply_photo(photo=open(BOARD_IMAGE, 'rb'), caption='تعداد بازیکنان رو انتخاب کن:', reply_markup=reply_markup)
    games[chat_id]['message_id'] = msg.message_id
    return SELECT_MODE

# انتخاب حالت
async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    mode = int(query.data.split('_')[1])
    games[chat_id]['mode'] = mode
    
    keyboard = [
        [InlineKeyboardButton("آسان", callback_data='level_easy')],
        [InlineKeyboardButton("سخت", callback_data='level_hard')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = 'سطح بازی رو انتخاب کن:\n\nآسان: از خانه ۱ شروع می‌شه بدون نیاز به ۶.\nسخت: باید تاس ۶ بزنی تا وارد بشی.'
    await query.edit_message_caption(caption=caption, reply_markup=reply_markup)
    return SELECT_LEVEL

# انتخاب سطح
async def select_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    level = query.data.split('_')[1]
    games[chat_id]['level'] = level
    
    mode = games[chat_id]['mode']
    emoji_buttons = [[InlineKeyboardButton(emoji, callback_data=f'emoji_{i}')] for i, emoji in enumerate(EMOJIS[:mode])]
    reply_markup = InlineKeyboardMarkup(emoji_buttons)
    caption = f'هر کاربر یکی از ایموجی‌ها رو انتخاب کن (تا {mode} نفر). تکراری نمی‌تونی انتخاب کنی!'
    await query.edit_message_caption(caption=caption, reply_markup=reply_markup)
    return SELECT_EMOJI

# انتخاب ایموجی
async def select_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    emoji_idx = int(query.data.split('_')[1])
    emoji = EMOJIS[emoji_idx]
    
    game = games[chat_id]
    if emoji in game['selected_emojis'].values():
        await query.edit_message_text('این ایموجی قبلاً انتخاب شده! یکی دیگه انتخاب کن.')
        return SELECT_EMOJI
    
    if str(user_id) in game['emojis'] and game['emojis'][str(user_id)] is not None:
        await query.edit_message_text('تو قبلاً انتخاب کردی! منتظر بقیه باش.')
        return SELECT_EMOJI
    
    game['emojis'][str(user_id)] = emoji
    game['selected_emojis'][str(user_id)] = emoji
    game['players'].append(user_id)
    
    if len(game['players']) == game['mode']:
        await start_game(chat_id, query)
        return PLAYING
    else:
        remaining = game['mode'] - len(game['players'])
        caption = f'انتخاب شد: {emoji}\n{remaining} نفر دیگه انتخاب کنن.'
        await query.edit_message_caption(caption=caption, reply_markup=query.message.reply_markup)
        return SELECT_EMOJI

# شروع بازی
async def start_game(chat_id: int, query):
    game = games[chat_id]
    caption = f'بازی شروع شد! سطح: {game["level"]}\nنوبت: {query.from_user.first_name}\nتاس رو بنداز!'
    keyboard = [[InlineKeyboardButton("🎲 تاس رو بندازید", callback_data='roll_dice')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bio = update_board_image(game['positions'], game['emojis'])
    await query.message.reply_photo(photo=bio, caption=caption, reply_markup=reply_markup)

# پرتاب تاس
async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    game = games[chat_id]
    if user_id != game['players'][game['current_player']]:
        await query.edit_message_caption(caption=query.message.caption + '\n\nهنوز نوبت شما نرسیده عزیز🥸')
        return PLAYING
    
    dice = random.randint(1, 6)
    player_pos = game['positions'][str(user_id)]
    
    new_pos = player_pos + dice
    
    if game['level'] == 'hard' and player_pos == 0:
        if dice != 6:
            await query.edit_message_caption(caption=f'{query.from_user.first_name} تاس {dice} انداخت، اما برای ورود نیاز به ۶ داری!\nنوبت بعدی.')
            game['current_player'] = (game['current_player'] + 1) % len(game['players'])
            return PLAYING
        else:
            new_pos = 1
    
    if new_pos > 100:
        new_pos = player_pos
    
    while new_pos in SNAKES_LADDERS:
        new_pos = SNAKES_LADDERS[new_pos]
    
    game['positions'][str(user_id)] = new_pos
    
    if new_pos >= 100:
        caption = f'🎉 {query.from_user.first_name} برنده شد! به ۱۰۰ رسید.\nبازی تموم!'
        keyboard = []
        reply_markup = InlineKeyboardMarkup(keyboard)
        bio = update_board_image(game['positions'], game['emojis'])
        await query.edit_message_media(media=InputMediaPhoto(bio, caption=caption), reply_markup=reply_markup)
        del games[chat_id]
        return ConversationHandler.END
    
    emoji = game['emojis'][str(user_id)]
    caption = f'{query.from_user.first_name} ({emoji}) تاس {dice} انداخت و به {new_pos} رفت.\nنوبت: {game["players"][(game["current_player"] + 1) % len(game["players"])]["first_name"]}'
    bio = update_board_image(game['positions'], game['emojis'])
    keyboard = [[InlineKeyboardButton("🎲 تاس رو بندازید", callback_data='roll_dice')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_media(media=InputMediaPhoto(bio, caption=caption), reply_markup=reply_markup)
    
    game['current_player'] = (game['current_player'] + 1) % len(game['players'])
    return PLAYING

# لغو
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if chat_id in games:
        del games[chat_id]
    await update.message.reply_text('بازی لغو شد.')
    return ConversationHandler.END

# Handler اصلی
def main():
    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('marpele', start_marple)],
        states={
            SELECT_MODE: [CallbackQueryHandler(select_mode, pattern='^mode_')],
            SELECT_LEVEL: [CallbackQueryHandler(select_level, pattern='^level_')],
            SELECT_EMOJI: [CallbackQueryHandler(select_emoji, pattern='^emoji_')],
            PLAYING: [CallbackQueryHandler(roll_dice, pattern='^roll_dice$')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
