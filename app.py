import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import logging

# ロギングの設定
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# LINE Botの設定
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google APIの設定
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# 認証情報のファイルパス
CREDENTIALS_PATH = '/etc/secrets/credentials.json'

# 認証情報をファイルから読み込む
with open(CREDENTIALS_PATH) as f:
    credentials_info = json.load(f)  # JSON形式で読み込む

# Credentialsオブジェクトを生成
credentials = Credentials.from_service_account_info(credentials_info)
service = build('sheets', 'v4', credentials=credentials)

# ユーザーのセッション管理
user_sessions = {}

# ステップの定数
STEP_INIT = 0
STEP_DATE = 1
STEP_RECEIPT_COUNT = 2
STEP_PAYER = 3
STEP_CUSTOMER_COUNT = 4
STEP_SALES = 5

# Google Sheetsに売上データを追加する関数
def add_sales_data_to_google_sheets(date, payer, customer_count, sales):
    try:
        sheet = service.spreadsheets()
        new_row = [[date, payer, customer_count, sales]]
        request = sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A:D",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": new_row}
        )
        response = request.execute()
        return response
    except Exception as e:
        logging.error(f"Error appending to Google Sheets: {e}")
        return None

# Webhookエンドポイント
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return ('OK', 200)

# メッセージを処理する
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    # セッションデータがなければ初期化
    if user_id not in user_sessions:
        user_sessions[user_id] = {"step": STEP_INIT, "data": {}}

    session = user_sessions[user_id]

    # ログ出力
    logging.info(f"User ID: {user_id}, Step: {session['step']}, User Message: {user_message}")

    # コマンドの処理
    if user_message.lower() == "リセット":
        user_sessions[user_id] = {"step": STEP_INIT, "data": {}}
        logging.info(f"User ID: {user_id} - Session reset.")
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text="入力をリセットしました。")
        )
        return

    if session["step"] == STEP_INIT:
        if user_message == "売上報告":
            session["step"] = STEP_DATE
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="営業日を入力してください（例: 2025/01/01）")
            )
        else:
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="「売上報告」と入力してください。")
            )

    elif session["step"] == STEP_DATE:
        session["data"]["date"] = user_message
        session["step"] = STEP_RECEIPT_COUNT
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text="伝票の枚数を入力してください。")
        )

    elif session["step"] == STEP_RECEIPT_COUNT:
        try:
            receipt_count = int(user_message)
            session["data"]["receipt_count"] = receipt_count
            session["step"] = STEP_PAYER
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="支払い者の名前を入力してください。")
            )
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="伝票の枚数は数字で入力してください。")
            )

    elif session["step"] == STEP_PAYER:
        session["data"]["payer"] = user_message
        session["step"] = STEP_CUSTOMER_COUNT
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text="伝票の人数を入力してください。")
        )

    elif session["step"] == STEP_CUSTOMER_COUNT:
        try:
            customer_count = int(user_message)
            session["data"]["customer_count"] = customer_count
            session["step"] = STEP_SALES
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="伝票の売上を入力してください。")
            )
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="伝票の人数は数字で入力してください。")
            )

    elif session["step"] == STEP_SALES:
        try:
            sales = int(user_message)
            session["data"]["sales"] = sales

            # Google Sheetsにデータを追加
            result = add_sales_data_to_google_sheets(
                session["data"]["date"], session["data"]["payer"],
                session["data"]["customer_count"], session["data"]["sales"]
            )

            # Google Sheetsへの保存成功/失敗メッセージ
            if result:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"売上データを記録しました！営業日: {session['data']['date']}, 支払い者: {session['data']['payer']}, 人数: {session['data']['customer_count']}, 売上: {session['data']['sales']} 円")
                )
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="Google Sheetsへの保存中にエラーが発生しました。")
                )

            # セッションリセット
            user_sessions[user_id] = {"step": STEP_INIT, "data": {}}
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text="売上は数字で入力してください。")
            )
    else:
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text="不明な入力です。もう一度お試しください。")
        )

@app.route("/", methods=["GET"])
def home():
    return "Welcome to the LINE Bot!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)