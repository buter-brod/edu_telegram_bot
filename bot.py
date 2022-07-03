# -*- coding: utf-8 -*-
import json
import config
import telebot
import re
import time
import traceback
from pathlib import Path
from datetime import datetime

running_bot = None

# set to 2 minutes for now
seconds_to_update_last_contact_timestamp = 60*2
seconds_to_launch_maintenance = 60*2

repeat_lesson_suggestion = "repeat_lesson_suggestion"

not_admin_err_msg = "(error, not admin)"


class State:
    def __init__(self):
        self.latest_maintenance_time = 0


class Filenames:
    pass


Filenames.all_lessons = "englibot_all_lessons.json"
Filenames.lessons = "englibot_lessons_test.json"
Filenames.misc = "englibot_misc.json"
Filenames.players = "englibot_players.json"
Filenames.admins = "englibot_admins.json"
Filenames.contacts = "englibot_contacts.json"
Filenames.fileids = "englibot_fileids.json"
Filenames.feedback = "englibot_feedback.json"


class Info:
    def __init__(self):
        self.players = {}
        self.lessons = []
        self.lessons_map = {}
        self.contacts = {}
        self.fileids = {}
    
    
info: Info = Info()
state = State()


def read_from_file(filename, create=True):
    try:
        f = open(filename, "r", encoding="utf-8")
        contents = f.read()
        f.close()
        return contents
    except FileNotFoundError:
        if create:
            f = open(filename, "w+")
            f.close()
        return ""


def write_to_file(filename, what):
    f = open(filename, "w+", encoding="utf-8")
    
    if isinstance(what, list):
        str_list = [str(val) for val in what]
        f.writelines(str_list)
    else:
        f.write(str(what))
    
    f.close()


def reportAdminsAnException(chat_id, ex):
    username = get_username_by_chat_id(chat_id)
    whom = username if username != "" else str(chat_id)
    tell_admins("Error while sending message to : @{}, exception: {}".format(whom, str(ex)))


def send_raw_txt(chat_id, text, kb=None):
    try:
        if kb:
            running_bot.send_message(chat_id, text, parse_mode='html', reply_markup=kb)
        else:
            running_bot.send_message(chat_id, text, parse_mode='html')
    except Exception as ex:
        reportAdminsAnException(chat_id, ex)
        running_bot.send_message(chat_id, str(ex))


def substitute_text(player_id, text):
    
    if player_id not in info.players:
        return text
    
    lesson = get_current_lesson(player_id)
    if lesson is not None:
        lesson_score = get_curr_score(player_id, lesson["id"])
        text = text.replace("[lesson_score]", str(lesson_score))

    overall_score = get_overall_score(player_id)
    max_score = get_max_score(player_id)
    player_info = info.players[player_id]

    name_to_replace = player_info["telegramID"]
    if "name" in player_info:
        name_to_replace = player_info["name"]
    text = text.replace("[player_name]", name_to_replace)
    
    text = text.replace("[max_score]", str(max_score))
    text = text.replace("[overall_score]", str(overall_score))
    
    gender_regex = re.compile('^.*?(\\[\\[(.*?)\\]\\[(.*?)\\]\\]).*?$', re.DOTALL)
    gendered_exp_match = re.match(gender_regex, text)
    while gendered_exp_match is not None:
        groups = gendered_exp_match.groups()
        if groups[0] is not None:
            gendered_txt = ["", ""]
            full_txt = groups[0]
            gendered_txt[0] = groups[1]
            gendered_txt[1] = groups[2]
            gender_id = info.players[player_id]["gender"]
            new_text = gendered_txt[gender_id]
        
            text = text.replace(full_txt, new_text)
            gendered_exp_match = re.match(gender_regex, text)
        
    return text


def send_msg(chat_id, player_id, text, replies, video_attachment="", photo_attachment="", document_attachment="",
             audio_attachment="", album_attachment=None):
    
    if album_attachment is None:
        album_attachment = []
    
    if player_id in info.players:
        text = substitute_text(player_id, text)
  
    for ind in range(len(replies)):
        answer_as_list = list(replies[ind])
        answer_as_list[1] = substitute_text(player_id, answer_as_list[1])
        replies[ind] = tuple(answer_as_list)
    
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    for answer in replies:
        reply_id = str(answer[0])
        reply_text = answer[1]
        callback_btn = telebot.types.InlineKeyboardButton(text=reply_text, callback_data=reply_id)
        keyboard.add(callback_btn)

    def tryopen_func(file_name, disable_cache=True):
        if not disable_cache and info.fileids is not None:
            if file_name in info.fileids:
                return info.fileids[file_name]

        try:
            opened_file = open(file_name, "rb")
            return opened_file
        except Exception as ex:
            send_raw_txt(chat_id, "(error, file not found {})".format(file_name))

    try:

        if audio_attachment != "":
            audio_file = tryopen_func(audio_attachment)
            if audio_file:
                running_bot.send_audio(chat_id, audio=audio_file, parse_mode='html', caption=text, reply_markup=keyboard)
                
        elif document_attachment != "":
            document_file = tryopen_func(document_attachment)
            if document_file:
                running_bot.send_document(chat_id, data=document_file, parse_mode='html', caption=text, reply_markup=keyboard)
                
        elif photo_attachment != "":
            photo_file = tryopen_func(photo_attachment)
            if photo_file:
                running_bot.send_photo(chat_id, photo_file, parse_mode='html', caption=text, reply_markup=keyboard)
                
        elif video_attachment != "":
            video_file = tryopen_func(video_attachment)
            if video_file:
                running_bot.send_video(chat_id, video_file, parse_mode='html', caption=text, reply_markup=keyboard, timeout=100)
                # todo: use file_id
            
        elif album_attachment:
            files = []
            
            if not isinstance(album_attachment, list):
                text = text + "\n--- ERROR with album attachment, not a list ---"
            else:
                for photo_filename in album_attachment:
                    photo_file = tryopen_func(photo_filename, disable_cache=True)
                    if photo_file:
                        files.append(telebot.types.InputMediaPhoto(photo_file))
    
            if len(files) > 0:
                running_bot.send_media_group(chat_id, files)
            
            if text and text != "":
                send_raw_txt(chat_id, text, keyboard)
            else:
                if not can_proceed_immediately(player_id):
                    send_raw_txt(chat_id, "(error, cannot attach buttons to photo album without text)")
        else:
            send_raw_txt(chat_id, text, keyboard)
    
    except Exception as ex:
        reportAdminsAnException(chat_id, ex)


def parse_fileids():
    fileids_file_str = read_from_file(Filenames.fileids)
    if fileids_file_str != "":
        fileids_json = json.loads(fileids_file_str)
        info.fileids = fileids_json


def parse_all_lessons():
    all_lessons_file_str = read_from_file(Filenames.all_lessons)
    all_lessons_json = json.loads(all_lessons_file_str)
    all_lessons_list = all_lessons_json["lessons"]
    
    info.lessons = []
    
    for lesson_filename in all_lessons_list:
        lesson_file_str = read_from_file(lesson_filename, create=False)
        if lesson_file_str != "":
            lesson_info = json.loads(lesson_file_str)
            info.lessons.append(lesson_info)
            lesson_id = lesson_info["id"]
            info.lessons_map[lesson_id] = lesson_info
    

def parse_lessons():
    lessons_file_str = read_from_file(Filenames.lessons)
    lessons_json = json.loads(lessons_file_str)
    info.lessons = lessons_json["lessons"]


def parse_players():
    players_file_str = read_from_file(Filenames.players)
    players_json = json.loads(players_file_str)
    info.players = players_json["players"]
    
    
def parse_feedback():
    feedback_file_str = read_from_file(Filenames.feedback)
    if feedback_file_str != "":
        feedback_json = json.loads(feedback_file_str)
        info.feedback = feedback_json
    else:
        info.feedback = {}
    

def parse_contacts():
    contacts_file_str = read_from_file(Filenames.contacts)
    if contacts_file_str != "":
        info.contacts = json.loads(contacts_file_str)


def save_feedback():
    feedback_serialized = json.dumps(info.feedback, ensure_ascii=False, indent=1)
    write_to_file(Filenames.feedback, feedback_serialized)


def save_fileids():
    fileids_serialized = json.dumps(info.fileids, ensure_ascii=False, indent=1)
    write_to_file(Filenames.fileids, fileids_serialized)


def save_contacts():
    contacts_serialized = json.dumps(info.contacts, ensure_ascii=False, indent=1)
    write_to_file(Filenames.contacts, contacts_serialized)


def save_players():
    players_to_save = {"players": info.players}
    players_serialized = json.dumps(players_to_save, ensure_ascii=False, indent=1)
    write_to_file(Filenames.players, players_serialized)


def parse_misc():
    misc_file_str = read_from_file(Filenames.misc)
    if misc_file_str != "":
        info.misc = json.loads(misc_file_str)


def parse_admins():
    admins_file_str = read_from_file(Filenames.admins)
    if admins_file_str != "":
        info.admins = json.loads(admins_file_str)["admins"]
    pass


def load_configs():
    parse_fileids()
    parse_contacts()
    parse_all_lessons()
    parse_players()
    parse_misc()
    parse_admins()
    parse_feedback()


def launch_bot():
    
    load_configs()
    bot = telebot.TeleBot(config.token, threaded=False)
    return bot


def on_gender_set(player_id, gender):
    info.players[player_id]["gender"] = gender
   
    plan = info.players[player_id]["plan"]
    
    if plan > 0:
        info.players[player_id]["current_service_message"] = "skip_1_lesson"
        save_players()
        skip_lesson_text =  info.misc["strings"]["msg_skip_1st_lesson_prompt"]
        chat_id = get_chat_id_by_username(player_id)
        send_msg(chat_id, player_id, skip_lesson_text, [("skip1_ok", info.misc["strings"]["msg_skip_1st_lesson_prompt_yes"]),
                                                        ("skip1_no", info.misc["strings"]["msg_skip_1st_lesson_prompt_no"])])
        return

    info.players[player_id]["current_service_message"] = ""
    init_player_state(player_id, send=True)


def on_name_confirmed(player_id):
    chat_id = get_chat_id_by_username(player_id)
    select_gender_text = info.misc["strings"]["msg_hello_gender"]
    send_msg(chat_id, player_id, select_gender_text, [("gender0", info.misc["strings"]["msg_hello_female"]),
                                                      ("gender1", info.misc["strings"]["msg_hello_male"])])
    info.players[player_id]["current_service_message"] = "msg_gender"
    save_players()
    

def on_name_entered(player_id, name):
    info.players[player_id]["name"] = name
    confirm_text = info.misc["strings"]["msg_hello_name_confirm"]
    info.players[player_id]["current_service_message"] = "msg_hello_name_confirm"
    save_players()

    chat_id = get_chat_id_by_username(player_id)
    ok_text = info.misc["strings"]["msg_hello_name_ok"]
   
    send_msg(chat_id, player_id, confirm_text, [("name_ok", ok_text)])
    

def new_user_introduction(player_id):
    
    if player_id not in info.players:
        add_user(player_id, -1, 0)
        tell_admins("New user just arrived: @{}".format(player_id))
    
    chat_id = get_chat_id_by_username(player_id)
    
    plan = info.players[player_id]["plan"]
    
    hello_text = info.misc["strings"]["msg_hello_trial_access" if plan == 0 else "msg_hello_full_access"]

    info.players[player_id]["current_service_message"] = "msg_hello"
    save_players()
    send_msg(chat_id, player_id, hello_text, [])


def on_user_start_bot(chat_info):
    
    contact_ok = check_contact(chat_info)
    
    if not contact_ok:
        return
    
    player_id = chat_info.username
    
    msg = get_current_message(player_id)
    if msg is not None:
        # this user already played in past, we will repeat last question, player could have deleted chat already
        send_current_messages_to_player(player_id)
    else:
        # will start from beginning
        new_user_introduction(player_id)
    

def get_next_lesson(curr_lesson_id):
    next_lesson_ind = 0
    for ind in range(len(info.lessons)):
        if info.lessons[ind]["id"] == curr_lesson_id:
            next_lesson_ind = ind + 1
    
    if next_lesson_ind < len(info.lessons):
        return info.lessons[next_lesson_ind]
        
    return ""


def get_prev_message_id(lesson, curr_id):
    flow = lesson["flow"]
    curr_msg_index = 0
    for ind in range(len(flow)):
        if flow[ind]["id"] == curr_id:
            curr_msg_index = ind
            break
    prev_msg_index = curr_msg_index - 1
    prev_msg_id = ""
    if prev_msg_index >= 0:
        prev_msg_id = flow[prev_msg_index]["id"]
    
    return prev_msg_id


def get_next_message_id(lesson, curr_id):
    flow = lesson["flow"]
    curr_msg_index = 0
    for ind in range(len(flow)):
        if flow[ind]["id"] == curr_id:
            curr_msg_index = ind
            break
    next_msg_index = curr_msg_index + 1
    next_msg_id = ""
    if next_msg_index < len(flow):
        next_msg_id = flow[next_msg_index]["id"]
        
    return next_msg_id


def get_current_lesson(player_id):
    if player_id not in info.players or "current_lesson" not in info.players[player_id]:
        return None
    
    lesson_id = info.players[player_id]["current_lesson"]
    lesson_index = 0
    for ind in range(len(info.lessons)):
        if info.lessons[ind]["id"] == lesson_id:
            lesson_index = ind
            break
    
    lesson = info.lessons[lesson_index]
    return lesson


def get_message_by_id(lesson, message_id):
    flow = lesson["flow"]
    for message in flow:
        if message["id"] == message_id:
            return message


def get_service_message(player_id):
    if player_id not in info.players or "current_service_message" not in info.players[player_id]:
        return ""
    
    srv_msg_id = info.players[player_id]["current_service_message"]
    return srv_msg_id


def get_current_message(player_id):
   
    lesson = get_current_lesson(player_id)
    
    if lesson is None:
        return None
    
    if player_id not in info.players or "current_message" not in info.players[player_id]:
        return None
    
    msg_id = info.players[player_id]["current_message"]
    msg = get_message_by_id(lesson, msg_id)
    return msg
    
    
def set_current_lesson(player_id, lesson_info, send=False):
    lesson_id = lesson_info["id"]
    if lesson_id != "":
        info.players[player_id]["current_lesson"] = lesson_id
        info.players[player_id]["current_message"] = ""
        init_player_state(player_id, send)
    else:
        pass


def proceed_to_next_lesson(player_id, send=False):
    
    current_lesson = get_current_lesson(player_id)
    lesson_id = current_lesson["id"]
    next_lesson = get_next_lesson(lesson_id)
    if next_lesson != "":
        set_current_lesson(player_id, next_lesson, send)
    else:
        send_raw_txt(get_chat_id_by_username(player_id), "(error), no next lesson")


def is_msg_available_for_plan(player_id, lesson, msg_id):
    if msg_id == "":
        return True

    player_info = info.players[player_id]
    player_plan = 0 if "plan" not in player_info else player_info["plan"]
    next_message = get_message_by_id(lesson, msg_id)

    if next_message == "":
        return True

    if "min_plan" in next_message and int(next_message["min_plan"]) > player_plan:
        return False
    
    return True
    

def proceed_to_next_question(player_id, send=False):
    lesson = get_current_lesson(player_id)
    message = get_current_message(player_id)
    player_info = info.players[player_id]
    
    next_msg_id = get_next_message_id(lesson, message["id"])
    available = is_msg_available_for_plan(player_id, lesson, next_msg_id)
    while not available:
        next_msg_id = get_next_message_id(lesson, next_msg_id)
        available = is_msg_available_for_plan(player_id, lesson, next_msg_id)
    
    if "attempts_made" in player_info:
        player_info["attempts_made"] = 0
    
    if "wait_for_simple_reply" in player_info:
        player_info["wait_for_simple_reply"] = 0

    if next_msg_id is None or next_msg_id == "":
        
        next_lesson = get_next_lesson(lesson["id"])
        if next_lesson != "":
            if info.players[player_id]["plan"] < 1:
                # trial, unable to proceed
                end_of_trial_text = info.misc["strings"]["msg_trial_end"]
                chat_id = get_chat_id_by_username(player_id)
                send_msg(chat_id, player_id, end_of_trial_text, [])
                return
    
            curr_score = get_curr_score(player_id, lesson["id"])
            if "score_threshold" in lesson and "msg_score_too_low" in info.misc["strings"] and curr_score < lesson["score_threshold"]:
                player_info["current_message"] = repeat_lesson_suggestion
            else:
                proceed_to_next_lesson(player_id)
        else:
            # the course is over, no next lesson
            if "restarted" not in info.players[player_id]:
                info.players[player_id]["current_service_message"] = "msg_congrats_1"
            else:
                info.players[player_id]["current_service_message"] = "msg_congrats_2"
    else:
        # just ordinary next message in lesson flow
        player_info["current_message"] = next_msg_id

    save_players()

    if send:
        send_current_messages_to_player(player_id)
    
    
def message_can_proceed_immediately(message):
    proceed_immediately = message \
                          and "reply" not in message \
                          and "simple_reply" not in message \
                          and "answers" not in message
    return proceed_immediately
    

def can_proceed_immediately(player_id):
    message = get_current_message(player_id)
    proceed_immediately = message_can_proceed_immediately(message)
    return proceed_immediately


def proceed_to_next_questions_and_send(player_id):
    proceed_immediately = True
    
    while proceed_immediately:
        proceed_to_next_question(player_id, True)
        proceed_immediately = can_proceed_immediately(player_id)


def get_max_score_for_lesson(lesson):
    if lesson is None:
        return 0

    if "max_score" not in lesson:
        count_max_scores()
        
    return lesson["max_score"]
    

def get_max_score_overall():
    score = 0
    for lesson in info.lessons:
        lesson_score = get_max_score_for_lesson(lesson)
        score = score + lesson_score
    
    return score
    
   
def get_max_score(player_id):
    lesson = get_current_lesson(player_id)
    score = get_max_score_for_lesson(lesson)
    return score


def get_overall_score(player_id):
    player_info = info.players[player_id]
    if "scores" not in player_info:
        return 0

    score = 0
    for lesson_id, lesson_score in player_info["scores"].items():
        score = score + lesson_score
    
    return score


def get_curr_score(player_id, lesson_id):
    
    if player_id not in info.players:
        return 0
    
    player_info = info.players[player_id]
    if "scores" not in player_info:
        player_info["scores"] = {}

    curr_score = 0

    if lesson_id in player_info["scores"]:
        curr_score = player_info["scores"][lesson_id]
        
    return curr_score
 

def add_score(player_id, score):
    lesson = get_current_lesson(player_id)
    lesson_id = lesson["id"]
    curr_score = get_curr_score(player_id, lesson_id)
    curr_score = curr_score + score
    player_info = info.players[player_id]
    player_info["scores"][lesson_id] = curr_score
    

def on_answer(player_id, correct):
    player_info = info.players[player_id]
    attempt = 0 if "attempts_made" not in player_info else player_info["attempts_made"]
    message = get_current_message(player_id)
    chat_id = get_chat_id_by_username(player_id)
    
    if correct:
        correct_text = message["correct_text"]
        
        score_to_add = info.misc["settings"]["score_for_1st_attempt" if attempt == 0 else "score_for_2nd_attempt"]
        add_score(player_id, score_to_add)

        correct_text = substitute_text(player_id, correct_text)
        send_raw_txt(chat_id, correct_text)
        
        if "simple_reply_to_explanation_after_correct" in message and "explanation_text" in message:
            simple_reply_to_explanation = message["simple_reply_to_explanation_after_correct"]
            send_msg(chat_id, player_id, message["explanation_text"], [(message["id"], simple_reply_to_explanation)])
            player_info["wait_for_simple_reply"] = 1
        else:
            proceed_to_next_questions_and_send(player_id)
    else:
        if "incorrect_1_text" in message:
            incorrect_text = message["incorrect_1_text"] if attempt == 0 else (message["incorrect_2_text"] if "incorrect_2_text" in message else message["incorrect_1_text"])
            incorrect_text = substitute_text(player_id, incorrect_text)
            send_raw_txt(chat_id, incorrect_text)
        
        # check if another attempt is possible
        attempts_possible = ("single_attempt" not in message) and (("answers" in message) or (
                    "reply" in message and len(message["reply"]) > 2))
        
        if not attempts_possible or attempt > 0:
            if "explanation_text" in message and "simple_reply_to_explanation_after_incorrect" in message:
                simple_reply_to_explanation = message["simple_reply_to_explanation_after_incorrect"]
                send_msg(chat_id, player_id, message["explanation_text"], [(message["id"], simple_reply_to_explanation)])
                player_info["wait_for_simple_reply"] = 1
            else:
                proceed_to_next_questions_and_send(player_id)
        else:
            player_info["attempts_made"] = attempt + 1
            
    save_players()


def init_player_state(player_id, send=False):
    player_info = info.players[player_id]
    if "current_lesson" not in player_info or player_info["current_lesson"] == "":
        player_info["current_lesson"] = info.lessons[0]["id"]
        player_info["current_message"] = ""

    if "current_message" not in player_info or player_info["current_message"] == "":
        lesson = get_current_lesson(player_id)
        player_info["current_message"] = lesson["flow"][0]["id"]
        if "scores" in player_info:
            player_info["scores"].pop(lesson["id"], None)
        save_players()
    
    if send:
        send_current_messages_to_player(player_id)
        

def init_current_player_states(send=False):
    for player_id, player_info in info.players.items():
        init_player_state(player_id, send)


def is_admin(player_id):
    for admin_info in info.admins:
        if admin_info["id"] == player_id:
            return True
    
    return False


def tell(whom_list, what):

    if isinstance(whom_list, str):
        whom_list = [whom_list]
    
    success = False
    
    for who in whom_list:
        chat_id = get_chat_id_by_username(who)
    
        if chat_id < 1:
            continue
    
        if isinstance(what, str):
            send_raw_txt(chat_id, what)
        else:
            running_bot.forward_message(chat_id, what.chat.id, what.message_id)

        success = True
        
    return success


def send_current_messages_to_player(player_id):
    send_current_message_to_player(player_id)
    can_proceed = can_proceed_immediately(player_id)
    if can_proceed:
        proceed_to_next_questions_and_send(player_id)
    

def tell_players(what):
    players = []
    for player_id, player_info in info.players.items():
        players.append(player_id)

    return tell(players, what)


def tell_admins(what):
    admins = []
    for admin_info in info.admins:
        admins.append(admin_info["id"])

    return tell(admins, what)


def restart_lesson(player_id, send=False):
    if player_id in info.players:
        player_info = info.players[player_id]
        lesson_id = get_current_lesson(player_id)["id"]
        if "scores" in player_info:
            player_info["scores"].pop(lesson_id, None)
        player_info.pop("current_message", None)
        info.players[player_id]["current_service_message"] = ""
        init_player_state(player_id, send)
        
        
def count_max_scores():
    max_score_per_question = info.misc["settings"]["score_for_1st_attempt"]

    text = ""
    
    for lesson in info.lessons:
        lesson["max_score"] = 0
        lesson_messages = lesson["flow"]
        for message in lesson_messages:
            is_question = "answers" in message or "reply" in message
            if is_question:
                lesson["max_score"] = lesson["max_score"] + max_score_per_question

        lesson_id = lesson["id"]
        text = text + lesson_id + ": " + str(lesson["max_score"]) + "\n"
    
    return text


def parse_command(command_text):
    command_match = re.match("^!(\S+)", command_text)
    if command_match is None or len(command_match.groups()) != 1:
        return None
    
    command_name = command_match.groups()[0]
    command_text = command_text[len(command_name) + 2:]
    
    command_args = command_text.split(' ') if len(command_text) > 0 else []
    return command_name, command_args


def cmd_go_msg(chat_info, args):
    if not is_admin(chat_info.username):
        return not_admin_err_msg
   
    if len(args) != 1:
        return "(error, invalid arguments, usage: !go_msg message_id)"

    player_id = chat_info.username
    lesson = get_current_lesson(player_id)
    msg_id = args[0]
    player_info = info.players[player_id]

    if player_info["current_message"] == msg_id:
        return "(error, already at this message)"
    
    flow = lesson["flow"]

    for msg in flow:
        if msg["id"] == msg_id:
            player_info["current_message"] = msg_id
    
            if "attempts_made" in player_info:
                player_info["attempts_made"] = 0
    
            if "wait_for_simple_reply" in player_info:
                player_info["wait_for_simple_reply"] = 0

            send_raw_txt(chat_info.id, "(success, moving to message {}".format(msg_id))
            send_current_message_to_player(player_id)
            save_players()
            return True
        
    return "(error, invalid msg id)"
    
    
def cmd_go_previous(chat_info, args):
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    player_id = chat_info.username
    
    lesson = get_current_lesson(player_id)
    message = get_current_message(player_id)
    prev_msg_id = get_prev_message_id(lesson, message["id"])
    
    if prev_msg_id == "":
        return "(error, no previous message)"
    
    player_info = info.players[player_id]
    
    player_info["current_message"] = prev_msg_id
    
    if "attempts_made" in player_info:
        player_info["attempts_made"] = 0

    if "wait_for_simple_reply" in player_info:
        player_info["wait_for_simple_reply"] = 0

    send_raw_txt(chat_info.id, "(success, moving to previous message {}".format(prev_msg_id))
    send_current_message_to_player(player_id)
    save_players()
    return True
    
    
def cmd_set_plan(chat_info, args):
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 2:
        return "(invalid args, please specify player_id and new plan)"
  
    player_id = args[0]
    
    if player_id not in info.players:
        return "(error: unknown user)"
    
    plan_str = args[1]

    if not plan_str.isnumeric():
        return "(error, payment plan should be numeric)"

    pay_plan = int(plan_str)
    
    info.players[player_id]["plan"] = pay_plan
    send_raw_txt(chat_info.id, "(success, plan set to {} for player @{})".format(str(pay_plan), player_id))

    text = info.misc["strings"]["msg_full_access_granted"]
    
    pay_plan_str = "plan" + str(pay_plan)
    pay_plan_str_replaced = info.misc["strings"][pay_plan_str] if pay_plan_str in  info.misc["strings"] else str(pay_plan)
    text = text.replace("[plan]", pay_plan_str_replaced)
    
    that_user_chat_id = get_chat_id_by_username(player_id)
    send_raw_txt(that_user_chat_id, text)
    send_current_message_to_player(player_id)
    save_players()
    
    return True

   
def cmd_max_score_point(chat_info, args):
    
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    max_scores_txt = count_max_scores()
    send_raw_txt(chat_info.id, max_scores_txt)
    return True


def cmd_repeat_for(chat_info, args):
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 1:
        return False

    for_who = args[0]
    if for_who not in info.players:
        return "(error, unknown player)"
    
    init_player_state(for_who, True)
    send_raw_txt(chat_info.id, "(success)")
    return True
    

def cmd_repeat(chat_info, args):
    player_id = chat_info.username
    if player_id not in info.players:
        return "(error, unknown player)"

    init_player_state(player_id, True)
    #send_current_message_to_player(player_id)
    return True


def cmd_tell(chat_info, args):
    
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 2:
        return "(cmd_tell syntax error. Usage example: !tell mikkens hi)"
    
    whom = args[0]
    what = ' '.join(args[1:])

    if whom == "admins":
        success = tell_admins(what)
    elif whom == "players":
        success = tell_players(what)
    else:
        success = tell(whom, what)
    
    if success:
        send_raw_txt(chat_info.id, "(success)")
        return True
    else:
        return "(error, unable to tell anyone)"
    

def cmd_ping(chat_info, args):
    send_raw_txt(chat_info.id, "pong")
    return True
    

def cmd_start_lesson(chat_info, args):
    
    player_id = chat_info.username

    if not is_admin(player_id):
        return not_admin_err_msg

    if len(args) != 1:
        return "(invalid arguments for start lesson command)"

    lesson_id_needed = args[0]
    
    if lesson_id_needed.isnumeric():
        # not lesson_id, but lesson index is given
        lesson_ind_needed = int(lesson_id_needed) - 1
        if lesson_ind_needed >= len(info.lessons) or lesson_ind_needed < 0:
            return "(invalid lesson num, we just have {} lessons so far".format(len(info.lessons))
        
        lesson_id_needed = info.lessons[lesson_ind_needed]["id"]
    
    if lesson_id_needed not in info.lessons_map:
        return "(error, unknown lesson {})".format(lesson_id_needed)
    
    send_raw_txt(chat_info.id, "(ok, starting lesson {} now)".format(lesson_id_needed))
    info.players[player_id]["current_service_message"] = ""
    set_current_lesson(player_id, info.lessons_map[lesson_id_needed])
    send_current_messages_to_player(player_id)
    return True


def cmd_skip_lesson(chat_info, args):
    
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    player_id = chat_info.username
    proceed_to_next_lesson(player_id, send=True)
    return True

def restart_all(player_id):
    player_info = info.players[player_id]
    player_info.pop("scores", None)
    player_info.pop("current_lesson", None)
    info.players[player_id]["current_service_message"] = ""
    if "restarted" in info.players[player_id]:
        info.players[player_id].pop("restarted")
    init_player_state(player_id, send=True)
    
    
def cmd_restart(chat_info, args):
    if len(args) < 1:
        return "(error, what exactly do you want to restart?)"
    
    player_id = chat_info.username
    
    whom = args[0]
    if whom == "lesson":
        restart_lesson(player_id, send=True)
        return True
    elif whom == "all":
        if player_id in info.players:
            restart_all(player_id)
        return True

    return "(error, what exactly do you want to restart?)"

def cmd_get_file(chat_info, args):
    
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 1:
        return "(error, please specify file name)"

    filename = args[0]
    file = None
    
    try:
        file = open(filename, "rb")
    except Exception as ex:
        return "(error, file not found)"

    try:
        running_bot.send_document(chat_info.id, file)
    except Exception as ex:
        return "(error, unable to send file)"
        
    return True


def cmd_remove_user(chat_info, args):
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 1:
        return "(error, please specify name)"

    player_id = args[0]
    removed_user = info.players.pop(player_id, None)

    if removed_user is not None:
        save_players()
        send_raw_txt(chat_info.id, "removed user " + player_id)
        return True
    else:
        return "(error: unknown user " + player_id + ")"
    
def add_user(id, gender, plan):

    if id in info.players:
        return False
    
    info.players[id] = {
        "telegramID": id,
        "gender": gender,
        "plan": plan
    }
    save_players()
    return True

def cmd_add_user(chat_info, args):
    
    if not is_admin(chat_info.username):
        return not_admin_err_msg
    
    if len(args) < 2:
        return "(error, please specify name and gender)"
    
    new_player_id = args[0]
    
    if new_player_id in info.players:
        return "(error, already have this user)"
    
    gender = 0 if args[1] == '0' else 1
    
    pay_plan_str = args[2] if len(args) == 3 else "0"
    
    if not pay_plan_str.isnumeric():
        return "(error, payment plan should be numeric)"
    
    pay_plan = int(pay_plan_str)
   
    add_ok = add_user(new_player_id, gender, pay_plan)
    if not add_ok:
        return "(error, unable to add user, could be existing one?)"
    
    send_raw_txt(chat_info.id, "added new user " + new_player_id)
    return True
   
    
def process_command(chat_info, text):
    
    command_info = parse_command(text)
    
    if not command_info:
        return False

    command_handlers = {
        "max_score_count": cmd_max_score_point,
        "repeat": cmd_repeat,
        "repeat_for": cmd_repeat_for,
        "tell": cmd_tell,
        "ping": cmd_ping,
        "start_lesson": cmd_start_lesson,
        "skip_lesson": cmd_skip_lesson,
        "restart": cmd_restart,
        "add_user": cmd_add_user,
        "remove_user": cmd_remove_user,
        "get_file": cmd_get_file,
        "set_plan": cmd_set_plan,
        "previous": cmd_go_previous,
        "go_msg": cmd_go_msg
    }

    command_name = command_info[0]
    command_args = command_info[1:][0]
    if command_name in command_handlers:
        handle_func = command_handlers[command_name]
        result = handle_func(chat_info, command_args)
        if result == True:
            return True
        elif isinstance(result, str):
            send_raw_txt(chat_info.id, result)
        else:
            send_raw_txt(chat_info.id, "(unknown command execution error)")
        
        return True
    
    return False
    

def process_service_message(chat_info, what):
    
    player_id = chat_info.username
    
    if player_id not in info.players:
        return False

    srv_msg = get_service_message(player_id)
    
    if srv_msg == "":
        return False
    
    if srv_msg == "msg_hello":
        on_name_entered(player_id, what)
        return True

    if srv_msg == "msg_hello_name_confirm":
        if what == "name_ok":
            on_name_confirmed(player_id)
        else:
            on_name_entered(player_id, what)
            
        return True
    
    if srv_msg == "msg_congrats_1":
        if what == "restart":
            restart_all(player_id)
            info.players[player_id]["current_service_message"] = ""
            info.players[player_id]["restarted"] = 1
            save_players()
        return True

    if srv_msg == "msg_congrats_2":
        return True
    
    if srv_msg == "skip_1_lesson":
        if what == "skip1_ok":
            init_player_state(player_id)
            proceed_to_next_lesson(player_id, send=True)
            info.players[player_id]["current_service_message"] = ""
            return True
        elif what == "skip1_no":
            info.players[player_id]["current_service_message"] = ""
            init_player_state(player_id, send=True)
            return True
    
    if srv_msg == "msg_gender":
        
        if what != "gender0" and what != "gender1":
            return False

        gender = 0 if what == "gender0" else 1
        on_gender_set(player_id, gender)
        return True
    
    return False


def on_text_message(chat_info, chat_message):
    
    text = chat_message.text
    text = text.replace("’", "'")
  
    if process_command(chat_info, text):
        return

    if process_service_message(chat_info, text):
        return

    player_id = chat_info.username
    
    if player_id not in info.players:
        return
    
    message = get_current_message(player_id)

    player_info = info.players[player_id]
    just_simple_reply_allowed = "wait_for_simple_reply" in player_info and player_info["wait_for_simple_reply"] == 1

    # check if that's an answer to text-reply question
    if not just_simple_reply_allowed and message and "answers" in message:
        correct = False
        for possible_answer in message["answers"]:
            if "text" in possible_answer and possible_answer["text"].lower() == text.lower():
                correct = "correct" in possible_answer and possible_answer["correct"] > 0
        on_answer(player_id, correct)
        return
       
    if player_id not in info.feedback:
        info.feedback[player_id] = []
    info.feedback[player_id].append({get_current_time(): text})
    save_feedback()
    
    tell_admins("(user @{}, while on {}, just sent some useless info to the bot):".format(player_id, message["id"] if message else "(no_message)"))
    tell_admins(chat_message)
    
    # todo: what did player mean by just texting something, if this message isn't any writing exercise?
    pass


def check_button_special_cases(chat_info, button_id):
    
    srv_msg_processed = process_service_message(chat_info, button_id)
    
    if srv_msg_processed:
        return True
    
    player_id = chat_info.username
    player_info = info.players[player_id]
    curr_msg_id = player_info["current_message"]
    
    if curr_msg_id == repeat_lesson_suggestion:
        if button_id == "repeat_lesson":
            restart_lesson(player_id, send=True)
        elif button_id == "go_next_lesson":
            proceed_to_next_lesson(player_id, send=True)
        else:
            return False

        return True
    
    if button_id == "msg_ok_i_ll_pay":
        send_raw_txt(chat_info.id, info.misc["strings"]["msg_you_d_better_go_work"])
        return True
    return False


def on_button_press(chat_info, call_data):
    button_msg_id = call_data
    
    special_case = check_button_special_cases(chat_info, button_msg_id)
    if special_case:
        return

    player_id = chat_info.username

    if player_id not in info.players:
        # error, who is this player and how come he has buttons to press?
        return

    message = get_current_message(player_id)
    
    if not message:
        send_raw_txt(chat_info.id, "unknown error on get_current_message player_id, please contact admin")
        return
    
    # check if it's a simple reply to lesson message
    if message["id"] == button_msg_id:
        proceed_to_next_questions_and_send(player_id)
    else:
        # now check if it's a reply to real question
        if "reply" not in message:
            # maybe some old (obsolete) button pressed?
            return

        player_info = info.players[player_id]
        if "wait_for_simple_reply" in player_info and player_info["wait_for_simple_reply"] == 1:
            return

        for reply_msg in message["reply"]:
            if "id" in reply_msg and reply_msg["id"] == button_msg_id:
                correct = "correct" in reply_msg and reply_msg["correct"] == 1
                on_answer(player_id, correct)
                return
        
        
def get_current_time():
    return (datetime.utcnow() - datetime.utcfromtimestamp(0)).total_seconds()


def send_set_username(chat_id):
    username_video = open("username_video.mp4", "rb")
    running_bot.send_video(chat_id, username_video, None, info.misc["strings"]["msg_no_username"])
    

def check_contact(chat_info):
    
    if chat_info.username == None:
        send_set_username(chat_info.id)
        return False
    
    current_time = get_current_time()
    
    if str(chat_info.id) not in info.contacts:
        info.contacts[str(chat_info.id)] = {
            "first_name": chat_info.first_name,
            "id": chat_info.id,
            "type": chat_info.type,
            "username": chat_info.username,
            "first_contact_timestamp": current_time,
            "last_contact_timestamp": current_time,
        }
        save_contacts()
    else:
        if info.contacts[str(chat_info.id)]["username"] == None and chat_info.username != None:
            info.contacts[str(chat_info.id)]["username"] = chat_info.username
        
        delta_contact_timestamp = current_time - info.contacts[str(chat_info.id)]["last_contact_timestamp"]
        if delta_contact_timestamp > seconds_to_update_last_contact_timestamp:
            info.contacts[str(chat_info.id)]["last_contact_timestamp"] = current_time
            save_contacts()
    
    return True
           

def get_username_by_chat_id(chat_id):
    for contact_id, contact_info in info.contacts.items():
        if contact_info["id"] == chat_id:
            return contact_info["username"]
    return ""


def get_chat_id_by_username(username):
    for contact_id, contact_info in info.contacts.items():
        if contact_info["username"] == username:
            return contact_info["id"]
    return 0
    

def send_current_message_to_player(player_id):
    player_info = info.players[player_id]
    message_id = player_info["current_message"]
    chat_id = get_chat_id_by_username(player_id)

    if "wait_for_simple_reply" in player_info:
        player_info["wait_for_simple_reply"] = 0

    srv_msg = info.players[player_id]["current_service_message"]
    if srv_msg == "msg_congrats_1" or srv_msg == "msg_congrats_2":
        congrats_msg = info.misc["strings"]["msg_congrats_1"] if srv_msg == "msg_congrats_1" else info.misc["strings"]["msg_congrats_2"]
        overall_score = get_overall_score(player_id)
        max_score_overall = get_max_score_overall()
        overall_score_percent = overall_score / max_score_overall * 100
        congrats_msg = congrats_msg.replace("[overall_score_percent]", f"{overall_score_percent:.1f}" )
    
        if srv_msg == "msg_congrats_1":
            send_msg(chat_id, player_id, congrats_msg, [("restart", info.misc["strings"]["msg_btn_restart"])])
        else:
            send_msg(chat_id, player_id, congrats_msg, [])
        return
     
    if message_id == repeat_lesson_suggestion:
        send_msg(chat_id, player_id, info.misc["strings"]["msg_score_too_low"], [
            ("repeat_lesson", info.misc["strings"]["repeat_lesson"]),
            ("go_next_lesson", info.misc["strings"]["go_next_lesson"])])
        return
    
    lesson_id = player_info["current_lesson"]
    
    lessons_with_this_id = [lesson for lesson in info.lessons if lesson["id"] == lesson_id]
    if len(lessons_with_this_id) != 1:
        # error WTF should be only 1 lesson with this ID
        return
   
    lesson = lessons_with_this_id[0]
    
    lesson_messages = lesson["flow"]
    lesson_messages_with_this_id = [msg for msg in lesson_messages if msg["id"] == message_id]
    
    if (len(lesson_messages_with_this_id) != 1):
        # error WTF should be exactly 1 msg with this id
        return
    
    message_in_lesson = lesson_messages_with_this_id[0]
    msg_text = message_in_lesson["text"] if "text" in message_in_lesson else ""

    replies = []
    if "simple_reply" in message_in_lesson:
        simple_reply = message_in_lesson["simple_reply"]
        simple_reply_obj = (message_id, simple_reply)
        replies.append(simple_reply_obj)
    elif "reply" in message_in_lesson:
        message_replies = message_in_lesson["reply"]
        replies = [(r["id"], r["text"]) for r in message_replies]
        
    if chat_id > 0:
        if "sticker_before_text" in message_in_lesson:
            sticker_id = message_in_lesson["sticker_before_text"]
            try:
                running_bot.send_sticker(chat_id, sticker_id)
            except Exception as ex:
                reportAdminsAnException(chat_id, ex)
                
            
        audio_attachment = message_in_lesson["audio"] if "audio" in message_in_lesson else ""
        video_attachment = message_in_lesson["video"] if "video" in message_in_lesson else ""
        photo_attachment = message_in_lesson["photo"] if "photo" in message_in_lesson else ""
        album_attachment = message_in_lesson["photos"] if "photos" in message_in_lesson else []
        document_attachment = message_in_lesson["document"] if "document" in message_in_lesson else ""
        try:
            send_msg(chat_id, player_id, msg_text,
                     replies=replies,
                     video_attachment=video_attachment,
                     photo_attachment=photo_attachment,
                     document_attachment=document_attachment,
                     audio_attachment=audio_attachment,
                     album_attachment=album_attachment)

        except Exception as ex_inst:
            try:
                send_raw_txt(chat_id, "(error in message {}, exception: {}".format(message_id, str(ex_inst)))
            except Exception as ex:
                pass
    else:
        # error
        pass

   
def maintenance():
    pass


def check_maintenance():
    current_time = get_current_time()
    if current_time - state.latest_maintenance_time > seconds_to_launch_maintenance:
        maintenance()
        state.latest_maintenance_time = current_time


def telegram_polling():
    
    while True:
        try:
            running_bot.polling()
            # running_bot.polling(none_stop=True, timeout=60) #constantly get messages from Telegram
        except Exception as ex:
            traceback_error_string = traceback.format_exc()
            try:
                print("BOT EXCEPTION: " + traceback_error_string)
                with open("Error.Log", "a") as err_file:
                    err_file.write("\r\n\r\n" + time.strftime("%c")+"\r\n<<ERROR polling>>\r\n" + traceback_error_string + "\r\n<<ERROR polling>>")
            except Exception as ex:
                pass
                # sorry

            running_bot.stop_polling()
            time.sleep(20)
    

def on_file_received(chat_id, username, filename, file_id):
    
    folder_name = ""
    filename = filename.rstrip('/')
    last_slash = filename.rfind('/')
    if last_slash >= 0:
        folder_name = filename[:last_slash]
        filename = filename[last_slash + 1:]
    
    full_path = filename
    if folder_name != "":
        try:
            Path(folder_name).mkdir(parents=True, exist_ok=True)
            full_path = folder_name + "/" + full_path
        except Exception as ex:
            send_raw_txt(chat_id, "(error, path invalid?)")
            return
 
    file_id_info = running_bot.get_file(file_id)

    will_reload_configs = "json" in filename
    
    if not will_reload_configs:
        # simple resources, could be big files, let's record ids
        info.fileids[full_path] = file_id_info.file_id
        save_fileids()
    
    try:
        downloaded_file = running_bot.download_file(file_id_info.file_path)
        with open(full_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        tell_admins("File saved - {}.\n{}\nCulprit: @{}".format(str(full_path), ("Configs reloaded!" if will_reload_configs else ""), username))
       
        if will_reload_configs:
            load_configs()
            
    except Exception as ex:
        running_bot.send_message(chat_id, "error saving file: " + str(ex))


def set_callbacks():
    @running_bot.message_handler(commands=['start'])
    def on_start(message):
        on_user_start_bot(message.chat)

    @running_bot.message_handler(content_types=['video'])
    def on_message(message):
        if not message.caption or message.caption == "":
            send_raw_txt(message.chat.id, "(error in uploading video, please specify path and name in caption)")
            return
        on_file_received(message.chat.id, message.chat.username, message.caption if message.caption is not None else "", message.video.file_id)

    @running_bot.message_handler(content_types=['audio'])
    def on_message(message):
        if not message.caption or message.caption == "":
            send_raw_txt(message.chat.id, "(error in uploading audio, please specify path and name in caption)")
            return
        on_file_received(message.chat.id, message.chat.username, message.caption if message.caption is not None else "",
                         message.audio.file_id)

    @running_bot.message_handler(content_types=['document'])
    def on_message(message):
        full_filename = (message.caption + "/" if message.caption is not None else "") + message.document.file_name
        on_file_received(message.chat.id, message.chat.username, full_filename, message.document.file_id)
    
    @running_bot.message_handler(content_types=['voice'])
    def on_message(message):
        player_id = message.chat.username
        if player_id in info.players:
            player_info = info.players[player_id]
            player_plan = 0 if "plan" not in player_info else player_info["plan"]
            min_plan = 0 if "min_plan_for_voice_forward" not in info.misc["settings"] else info.misc["settings"]["min_plan_for_voice_forward"]
            if player_plan >= min_plan:
                for admin_info in info.admins:
                    admin_id = admin_info["id"]
                    admin_chat_id = get_chat_id_by_username(admin_id)
        
                    curr_lesson = get_current_lesson(message.chat.username)
                    if curr_lesson is not None:
                        send_raw_txt(admin_chat_id, "voice input from @{}, lesson: {}".format(message.chat.username,
                                                                                              curr_lesson["id"]))
                        running_bot.forward_message(admin_chat_id, message.chat.id, message.message_id)
                        
    @running_bot.message_handler(content_types=["text"])
    def on_message(message):
        so_far_so_good = check_contact(message.chat)
        
        if not so_far_so_good:
            return
        
        on_text_message(message.chat, message)
        
    
    @running_bot.callback_query_handler(func=lambda call: True)
    def callback_inline(call):
        on_button_press(call.message.chat, call.data)
    

if __name__ == '__main__':
    running_bot = launch_bot()
    set_callbacks()

    telegram_polling()
    
    print("done")

