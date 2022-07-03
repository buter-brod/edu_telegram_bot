# edu_telegram_bot
Telegram bot (telebot-based) for teaching any stuff with support for tutor feedback. 
This bot was originally made for engligram blog (teaching English for Russians). 

Now I decided to make it open-source and free to use for any education purposes. I kept 1st lesson content as an example how to configure lessons and which media formats are supported.

How to use: 

0. there is a working instance of this bot, you can check it out at @EngligramBot and decide whether the functionality suits your needs.
1. add your telegram id into englibot_admins.json
2. set up cron or somwthing like that to re-launch bot when it crahes ^__________^ It's rare thing but sometimes telebot lib crashes due to some connectivity.
3. get familiar with commands:
!max_score_count
!repeat 
!repeat_for
!tell
!ping
!start_lesson
!skip_lesson
!restart
!add_user
!remove_user
!get_file 
!set_plan 
!previous
!go_msg

thanks to:
telebot lib
Nadia & Anya - the english teachers who helped with testing all the way.
