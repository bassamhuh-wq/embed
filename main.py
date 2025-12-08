import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- المتغيرات العامة والثوابت ---
user_sessions = {}
active_streams = {}
# يرجى استبدال هذا بمعرفات المسؤولين الخاصة بك
ADMIN_IDS = [1011696070, 669225576]
AUTHORIZED_USERS = set(ADMIN_IDS)

# --- دوال التحقق ---
async def check_authorized(update: Update):
    """التحقق من صلاحية المستخدم."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        reply_func = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
        await reply_func("🚫 اطلب صلاحية من المسؤول")
        return False
    return True

# --- معالجة الأوامر والرسائل ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorized(update):
        return
    
    keyboard = [
        [InlineKeyboardButton("📺 قائمة البثوث", callback_data="show_active")],
        [InlineKeyboardButton("➕ بدء بث جديد", callback_data="new_stream")],
        [InlineKeyboardButton("🎛 بث مخصص (720p)", callback_data="custom_stream")],
        [InlineKeyboardButton("🚀 بث عالي الجودة (1080p + شعار)", callback_data="high_quality_stream")]
    ]
    await update.message.reply_text("🎥 **مرحباً في بوت البث المباشر**\n\n✅ تم تحسين جميع البثوث لتتوافق مع Kick.\n\nاختر من الأزرار:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_authorized(update):
        return
    
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    # هذه الحالة تتعامل مع إرسال الرابط مباشرة بدون الضغط على زر
    if chat_id not in user_sessions:
        if text.startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
            user_sessions[chat_id] = {
                'step': 1, # البدء بطلب الهيدرات مباشرة
                'stream_type': 'normal', 
                'input_url': text,
                'reconnect_delay': 3, 
                'auto_reconnect': True,
                'stop_requested': False,
                'headers': {}
            }
            await update.message.reply_text("🌐 أرسل Referer (أو اضغط /skip للتخطي)")
            return
        else:
            await update.message.reply_text("❌ يرجى إرسال رابط صحيح أو استخدام الأزرار في القائمة")
        return
    
    session = user_sessions[chat_id]

    # الخطوة 0: الحصول على رابط الفيديو (بعد الضغط على زر)
    if session['step'] == 0:
        if text.startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
            session['input_url'] = text
            session['step'] = 1
            await update.message.reply_text("🌐 أرسل Referer (أو اضغط /skip للتخطي)")
        else:
            await update.message.reply_text("❌ يرجى إرسال رابط صحيح")
            
    # الخطوة 1: الحصول على Referer
    elif session['step'] == 1:
        if text != "/skip":
            session['headers']['referer'] = text
        session['step'] = 2
        await update.message.reply_text("🌐 أرسل Origin (أو اضغط /skip للتخطي)")
        
    # الخطوة 2: الحصول على Origin
    elif session['step'] == 2:
        if text != "/skip":
            session['headers']['origin'] = text
        session['step'] = 3
        await update.message.reply_text("🌐 أرسل User-Agent (أو اضغط /skip للتخطي)")
        
    # الخطوة 3: الحصول على User-Agent
    elif session['step'] == 3:
        if text != "/skip":
            session['headers']['user_agent'] = text
        session['step'] = 4
        await update.message.reply_text("🔧 أرسل الهيدرات المخصصة\n\n**يمكنك إدخالها بطريقتين:**\n\n1️⃣ **طريقة واحدة:** أرسل كل الهيدرات في سطر واحد مفصولة بفاصلة\nمثال: `Authorization=...,Host=...`\n\n2️⃣ **طريقة متعددة:** أرسل هيدر واحد ثم اضغط `n` للإضافة التالية أو اضغط `done` للإنهاء\n\nأو اضغط `0` للتخطي")
        
    # الخطوة 4: الحصول على الهيدرات المخصصة
    elif session['step'] == 4:
        if text.lower() == '0' or text.lower() == 'skip':
            session['step'] = 5 # الانتقال لطلب السيرفر
            await update.message.reply_text("🔗 أرسل رابط السيرفر (RTMP Server)")
        elif text.lower() == 'done':
            session['step'] = 5 # الانتقال لطلب السيرفر
            await update.message.reply_text("🔗 أرسل رابط السيرفر (RTMP Server)")
        elif text.lower() == 'n':
            await update.message.reply_text("🔧 أرسل الهيدر التالي (أو اضغط `done` للإنهاء)")
        elif '=' in text and ',' in text:
            # طريقة واحدة: كل الهيدرات في سطر واحد
            headers_list = text.split(',')
            for header in headers_list:
                if '=' in header:
                    key, value = header.split('=', 1)
                    session['headers'][key.strip()] = value.strip()
            session['step'] = 5 # الانتقال لطلب السيرفر
            await update.message.reply_text("✅ تم حفظ الهيدرات\n\n🔗 أرسل رابط السيرفر (RTMP Server)")
        elif '=' in text:
            # طريقة متعددة: هيدر واحد
            key, value = text.split('=', 1)
            session['headers'][key.strip()] = value.strip()
            await update.message.reply_text(f"✅ تم حفظ الهيدر: {key.strip()}\n\nأرسل الهيدر التالي أو اضغط `done` للإنهاء")
        else:
            await update.message.reply_text("❌ صيغة غير صحيحة. يرجى إدخال الهيدر بصيغة `key=value`")
    
    # الخطوة 5: الحصول على رابط السيرفر
    elif session['step'] == 5:
        session['server'] = text
        session['step'] = 6
        await update.message.reply_text("🔑 أرسل مفتاح البث (Stream Key)")
        
    # الخطوة 6: الحصول على مفتاح البث وبدء البث
    elif session['step'] == 6:
        session['stream_key'] = text
        await update.message.reply_text("⏳ جاري بدء البث...")
        asyncio.create_task(start_stream(update, context, session, user_id))
        if chat_id in user_sessions:
            del user_sessions[chat_id]

# --- دالة تشغيل البث (الكود الأكثر احترافية وثباتاً) ---
async def start_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, session, user_id, reconnect_attempt=0):
    chat_id = update.message.chat_id
    input_url = session['input_url']
    server = session['server']
    stream_key = session['stream_key']
    stream_type = session.get('stream_type', 'normal')
    auto_reconnect = session.get('auto_reconnect', True)
    reconnect_delay = session.get('reconnect_delay', 3)
    headers = session.get('headers', {})
    
    server = server.rstrip('/')
    output_url = f"{server}/{stream_key}"
    
    global_options = ["-nostdin"]
    loop_option = []
    if not input_url.startswith(('rtmp://', 'rtsp://')):
        loop_option = ['-stream_loop', '-1'] 

    input_options_before_i = []
    
    if input_url.startswith('http'):
        # استخدام الهيدرات المخصصة إذا تم إدخالها
        if 'user_agent' in headers:
            user_agent_string = headers['user_agent']
        else:
            user_agent_string = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
            
        input_options_before_i.extend(['-user_agent', user_agent_string])
        input_options_before_i.extend(['-timeout', '20000000']) 
        input_options_before_i.extend(['-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5']) 
        
        # إضافة الهيدرات المخصصة
        if 'referer' in headers:
            input_options_before_i.extend(['-headers', f"Referer: {headers['referer']}"])
        if 'origin' in headers:
            input_options_before_i.extend(['-headers', f"Origin: {headers['origin']}"])
        
        # إضافة الهيدرات المخصصة الأخرى
        for header_name, header_value in headers.items():
            if header_name not in ['referer', 'origin', 'user_agent']:
                input_options_before_i.extend(['-headers', f"{header_name}: {header_value}"])
        
        if input_url.endswith('.m3u8'):
            input_options_before_i.extend(['-protocol_whitelist', 'file,http,https,tcp,tls,crypto,pipe,hls'])
            input_options_before_i.extend(['-http_persistent', '1'])
            input_options_before_i.extend(['-allowed_extensions', 'ALL'])
            input_options_before_i.extend(['-max_reload', '5'])
            input_options_before_i.extend(['-fflags', '+genpts'])
    
    # --- إعدادات FFmpeg فائقة التوافق مع Kick ---
    # بناء الأمر حسب نوع البث
    
    if stream_type == "normal":
        cmd = [
            "ffmpeg", 
            *global_options,
            *loop_option, 
            *input_options_before_i, 
            "-i", input_url, 
            
            # --- إعدادات الفيديو المتوافقة ---
            "-c:v", "libx264",  
            "-preset", "veryfast",  # توازن بين الجودة والأداء
            "-tune", "zerolatency", 
            "-profile:v", "high",   # بروفايل قياسي للبث
            "-level", "4.0",        # مستوى متوافق
            "-pix_fmt", "yuv420p", 
            "-r", "30",  
            "-g", "60",             # إطار مفتاحي كل ثانيتين
            "-keyint_min", "60",     # أقل فترة بين الإطارات المفتاحية
            "-b:v", "2500k",         # بت ريت آمن
            "-maxrate", "2500k",     # أقصى بت ريت
            "-bufsize", "5000k",     # حجم المخزن المؤقت
            
            # --- إعدادات الصوت المتوافقة ---
            "-c:a", "aac",
            "-b:a", "128k", 
            "-ar", "44100", 

            # --- إعدادات الخرج والخرائط ---
            "-map", "0:v:0",         # اختر أول تيار فيديو
            "-map", "0:a:0",         # اختر أول تيار صوتي
            "-f", "flv", 
            "-flvflags", "no_duration_filesize", # إعدادات إضافية للـ FLV
            output_url
        ]
        await context.bot.send_message(chat_id, "✅ تم بدء البث! (بث عادي - متوافق مع Kick)")
    
    elif stream_type == "custom":
        cmd = [
            "ffmpeg", 
            *global_options,
            *loop_option, 
            "-re", # مهم للترميز المباشر
            *input_options_before_i, 
            "-i", input_url, 
            
            # --- إعدادات الفيديو مع فلتر التغيير ---
            "-vf", "scale=1280:720,format=yuv420p",
            "-c:v", "libx264", 
            "-preset", "veryfast", 
            "-tune", "zerolatency", 
            "-profile:v", "high",
            "-level", "4.0",
            "-pix_fmt", "yuv420p", 
            "-r", "30", # خفض الفريمات لزيادة الاستقرار
            "-g", "60", 
            "-keyint_min", "60",
            "-b:v", "3000k",         # بت ريت مناسب لـ 720p
            "-maxrate", "3000k",
            "-bufsize", "6000k",
            
            # --- إعدادات الصوت ---
            "-c:a", "aac", 
            "-b:a", "128k", 
            "-ar", "44100",

            # --- إعدادات الخرج والخرائط ---
            "-map", "0:v:0",
            "-map", "0:a:0",
            "-f", "flv",
            "-flvflags", "no_duration_filesize",
            output_url
        ]
        await context.bot.send_message(chat_id, "✅ تم بدء البث! (دقة 720p - متوافق مع Kick)")

    elif stream_type == "high_quality":
        logo_url = "https://www2.0zz0.com/2025/11/26/10/779206110.png"
        
        cmd = [
            "ffmpeg", 
            *global_options,
            *loop_option, 
            "-re", # مهم للترميز المباشر
            *input_options_before_i, 
            "-i", input_url, 
            "-i", logo_url, 
            
            # --- فلتر معقد مع تعريف خرائط واضح ---
            "-filter_complex", 
            "[0:v]scale=-1:1080:flags=bilinear,format=yuv420p[bg];[1:v]scale=250:-1[logo];[bg][logo]overlay=main_w-overlay_w-90:70[v]",
            
            # --- إعدادات الفيديو ---
            "-c:v", "libx264", 
            "-preset", "ultrafast", 
            "-tune", "zerolatency", 
            "-profile:v", "high",
            "-level", "4.2",
            "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709",
            "-color_range", "tv",

            "-r", "60", # خفض الفريمات لزيادة الاستقرار
            "-g", "120",
            "-keyint_min", "60",
            "-b:v", "7000k",         # بت ريت مناسب لـ 1080p
            "-maxrate", "8500k",
            "-bufsize", "14000k",
            
            # --- إعدادات الصوت ---
            "-c:a", "aac", 
            "-b:a", "160k", 
            "-ar", "48000",

            # --- إعدادات الخرج والخرائط ---
            "-map", "[v]",           # استخدم الفيديو من الفلتر
            "-map", "0:a:0",         # استخدم الصوت من المصدر الأصلي
            "-f", "flv",
            "-flvflags", "no_duration_filesize",
            output_url
        ]
        await context.bot.send_message(chat_id, "✅ تم بدء البث! (جودة عالية 1080p - متوافق مع Kick)")

    # إرسال إشعار للمسؤولين عند بدء بث جديد
    if user_id not in ADMIN_IDS and reconnect_attempt == 0:
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"📢 بدأ المستخدم `{user_id}` بثًا جديدًا من الدردشة `{chat_id}`.", parse_mode="Markdown")
            except:
                pass

    frame_msg = await context.bot.send_message(chat_id, "⌛️ جاري تحميل معلومات الفريم...")

    retcode = -1
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        active_streams[chat_id] = {
            "input_url": input_url,
            "output_url": output_url,
            "process": process,
            "frame_msg_id": frame_msg.message_id,
            "owner_id": user_id,
            "stream_type": stream_type,
            "session": session
        }
        
        error_lines = []
        
        while True:
            line = await process.stderr.readline()
            if not line:
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.5) 
                continue
            
            decoded = line.decode('utf-8', errors='ignore').strip()
            error_lines.append(decoded)
            if len(error_lines) > 500:
                error_lines.pop(0)
            
            if "fps=" in decoded:
                fps_match = re.search(r"fps=\s*(\d+\.?\d*)", decoded)
                time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", decoded)
                speed_match = re.search(r"speed=\s*([\d\.]+)x", decoded)

                fps = fps_match.group(1) if fps_match else "?"
                time_str = time_match.group(1) if time_match else "00:00:00"
                speed = speed_match.group(1) if speed_match else "?"

                if stream_type == 'custom':
                    stream_type_text = "🎛 بث مخصص (720p)"
                elif stream_type == 'high_quality':
                    stream_type_text = "🚀 بث عالي الجودة (1080p) + شعار"
                else:
                    stream_type_text = "📺 بث عادي"

                text_update = (
                    f"📊 **معلومات البث** ({stream_type_text})\n"
                    f"• الفريمات : {fps}\n"
                    f"• الوقت : {time_str}\n"
                    f"• السرعة : {speed}x"
                )

                seconds_part = 0
                try:
                    seconds_part = int(time_str.split(':')[-1].split('.')[0])
                except:
                    pass
                
                try:
                    if seconds_part % 10 == 0: 
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=frame_msg.message_id,
                            text=text_update,
                            parse_mode="Markdown"
                        )
                except:
                    pass

        retcode = await process.wait()
        
        if retcode == 0:
            await context.bot.send_message(chat_id, "✅ تم إنهاء البث بنجاح.")
        else:
            error_output = "\n".join(error_lines[-50:]) 
            full_error_msg = (
                f"⛔️ **توقف البث بخطأ** (كود: {retcode})\n\n"
                f"📝 **سجل الأخطاء (آخر 50 سطر):**\n"
                f"```\n{error_output}\n```"
            )
            
            if auto_reconnect and not session.get('stop_requested', False):
                reconnect_attempt += 1
                await context.bot.send_message(
                    chat_id, 
                    f"{full_error_msg}\n\n🔄 **محاولة إعادة الاتصال #{reconnect_attempt} بعد {reconnect_delay} ثواني...**", 
                    parse_mode="Markdown"
                )
                await asyncio.sleep(reconnect_delay)
                new_update = Update(update_id=update.update_id, message=update.message)
                asyncio.create_task(start_stream(new_update, context, session, user_id, reconnect_attempt))
            else:
                if not session.get('stop_requested', False):
                    await context.bot.send_message(chat_id, full_error_msg, parse_mode="Markdown")

    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ حدث خطأ أثناء البث: {str(e)}")
        
        if auto_reconnect and not session.get('stop_requested', False):
            reconnect_attempt += 1
            await context.bot.send_message(
                chat_id, 
                f"🔄 **محاولة إعادة الاتصال #{reconnect_attempt} بعد {reconnect_delay} ثواني...**"
            )
            await asyncio.sleep(reconnect_delay)
            new_update = Update(update_id=update.update_id, message=update.message)
            asyncio.create_task(start_stream(new_update, context, session, user_id, reconnect_attempt))
    
    finally:
        pass

# --- بقية دوال الأزرار والأوامر الإدارية ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data

    if user_id not in AUTHORIZED_USERS:
        await query.edit_message_text("🚫 ليس لديك صلاحية لاستخدام هذا البوت.")
        return

    if data == "show_active":
        visible_streams = {
            k: v for k, v in active_streams.items()
            if user_id in ADMIN_IDS or v["owner_id"] == user_id
        }
        
        if not visible_streams:
            await query.edit_message_text("📭 لا يوجد بث مباشر حالياً.")
        else:
            buttons = []
            for stream_chat_id, info in visible_streams.items():
                if info.get('stream_type') == 'custom':
                    stream_type_icon = "🎛"
                elif info.get('stream_type') == 'high_quality':
                    stream_type_icon = "🚀"
                else:
                    stream_type_icon = "📺"
                    
                row = [
                    InlineKeyboardButton(f"{stream_type_icon} تفاصيل", callback_data=f"info_{stream_chat_id}"),
                    InlineKeyboardButton(f"🆔 {info['owner_id']}", callback_data=f"user_{info['owner_id']}")
                ]
                if user_id in ADMIN_IDS or info['owner_id'] == user_id:
                    row.append(InlineKeyboardButton("⏹ إيقاف", callback_data=f"stop_stream_{stream_chat_id}"))
                buttons.append(row)
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="menu")])
            await query.edit_message_text("📋 **قائمة البثوث النشطة:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("stop_stream_"):
        target_chat_id = int(data.split("_")[-1])
        if target_chat_id not in active_streams:
            await query.edit_message_text("❌ البث غير موجود أو تم إيقافه بالفعل.")
            return
            
        stream = active_streams[target_chat_id]
        if user_id not in ADMIN_IDS and user_id != stream["owner_id"]:
            await query.edit_message_text("❌ لا يمكنك إيقاف هذا البث.")
            return
        
        stream['session']['stop_requested'] = True
            
        try:
            await query.edit_message_text("⏹️ جاري إيقاف البث...")
            process = stream["process"]
            if process.returncode is None:
                process.kill()
                await process.wait()

            del active_streams[target_chat_id]
            
            await query.edit_message_text("✅ تم إيقاف البث بنجاح.")
            
            try:
                await context.bot.delete_message(target_chat_id, stream["frame_msg_id"])
            except:
                pass
        except Exception as e:
            await query.edit_message_text(f"❌ فشل في إيقاف البث: {str(e)}")

    elif data.startswith("info_"):
        target_chat_id = int(data.split("_")[-1])
        if target_chat_id in active_streams:
            info = active_streams[target_chat_id]
            
            if info.get('stream_type') == 'custom':
                stream_type_text = "🎛 بث مخصص (720p)"
            elif info.get('stream_type') == 'high_quality':
                stream_type_text = "🚀 بث عالي الجودة (1080p) + شعار"
            else:
                stream_type_text = "📺 بث عادي"
                
            msg = (
                f"📡 **معلومات البث** ({stream_type_text})\n\n"
                f"🔗 **رابط الإدخال:**\n`{info['input_url']}`\n\n"
                f"🚀 **رابط الخروج:**\n`{info['output_url']}`\n\n"
                f"👤 **المالك:** {info['owner_id']}"
            )
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ البث غير موجود.")

    elif data.startswith("user_"):
        target_id = data.split("_")[1]
        await query.edit_message_text(f"🆔 **معرف المستخدم:** `{target_id}`", parse_mode="Markdown")

    elif data == "new_stream":
        user_sessions[chat_id] = {
            'step': 0, 
            'stream_type': 'normal',
            'reconnect_delay': 1, 
            'auto_reconnect': True,
            'stop_requested': False,
            'headers': {}
        }
        await query.edit_message_text("📥 **بدء بث جديد**\n\nأرسل رابط الفيديو (input video url)")

    elif data == "custom_stream":
        user_sessions[chat_id] = {
            'step': 0, 
            'stream_type': 'custom',
            'reconnect_delay': 1, 
            'auto_reconnect': True,
            'stop_requested': False,
            'headers': {}
        }
        await query.edit_message_text("🎛 **بدء بث مخصص**\n\n(جودة 720p - فريمات عالية)\n\nأرسل رابط الفيديو (input video url)")

    elif data == "high_quality_stream":
        user_sessions[chat_id] = {
            'step': 0, 
            'stream_type': 'high_quality',
            'reconnect_delay': 1, 
            'auto_reconnect': True,
            'stop_requested': False,
            'headers': {}
        }
        await query.edit_message_text("🚀 **بدء بث عالي الجودة**\n\n(جودة 1080p - إعدادات محسنة مع شعار القناة)\n\nأرسل رابط الفيديو (input video url)")

    elif data == "menu":
        keyboard = [
            [InlineKeyboardButton("📺 قائمة البثوث", callback_data="show_active")],
            [InlineKeyboardButton("➕ بدء بث جديد", callback_data="new_stream")],
            [InlineKeyboardButton("🎛 بث مخصص (720p)", callback_data="custom_stream")],
            [InlineKeyboardButton("🚀 بث عالي الجودة (1080p + شعار)", callback_data="high_quality_stream")]
        ]
        await query.edit_message_text("🎥 **القائمة الرئيسية**\n\nاختر من الأزرار:", reply_markup=InlineKeyboardMarkup(keyboard))
        
# --- أوامر الإدارة ---
async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🚫 فقط المسؤول يمكنه تنفيذ هذا الأمر.")
    
    if not context.args:
        return await update.message.reply_text("❗ يرجى إرسال ID المستخدم بعد الأمر.\nمثال: `/authorize 123456789`", parse_mode="Markdown")
    
    try:
        target_id = int(context.args[0])
        AUTHORIZED_USERS.add(target_id)
        await update.message.reply_text(f"✅ تم إعطاء صلاحية للمستخدم `{target_id}`.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❗ يرجى إرسال ID صحيح بعد الأمر.")

async def unauthorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🚫 فقط المسؤول يمكنه تنفيذ هذا الأمر.")
    
    if not context.args:
        return await update.message.reply_text("❗ يرجى إرسال ID المستخدم بعد الأمر.\nمثال: `/unauthorize 123456789`", parse_mode="Markdown")
    
    try:
        target_id = int(context.args[0])
        if target_id in ADMIN_IDS:
            return await update.message.reply_text("❗ لا يمكن إزالة صلاحية المسؤول.")
            
        AUTHORIZED_USERS.discard(target_id)
        await update.message.reply_text(f"✅ تم سحب صلاحية المستخدم `{target_id}`.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❗ يرجى إرسال ID صحيح بعد الأمر.")

async def list_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🚫 فقط المسؤول يمكنه تنفيذ هذا الأمر.")
    
    if AUTHORIZED_USERS:
        users_list = "\n".join([f"• `{user_id}`" for user_id in AUTHORIZED_USERS])
        await update.message.reply_text(f"👥 **المستخدمون المصرح لهم:**\n{users_list}", parse_mode="Markdown")
    else:
        await update.message.reply_text("📭 لا يوجد مستخدمون مصرح لهم.")

# --- التشغيل الرئيسي ---
if __name__ == '__main__':
    # تأكد من أن هذا هو توكن البوت الخاص بك
    TOKEN = '8570377475:AAFOxDb-HLWD9AyhmhH2DDeAok1AMUZHZ6c'
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("authorize", authorize))
    app.add_handler(CommandHandler("unauthorize", unauthorize))
    app.add_handler(CommandHandler("list_auth", list_authorized))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🤖 البوت يعمل الآن...")
    app.run_polling()