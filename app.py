import os
import json
import re
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

# LINE Botの設定
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 認証情報のファイルパス
CREDENTIALS_PATH = '/etc/secrets/credentials'

# 認証情報をファイルから読み込む
with open(CREDENTIALS_PATH) as f:
    credentials_info = json.load(f)

# Credentialsオブジェクトを生成
credentials = Credentials.from_service_account_info(credentials_info)

# Google Sheets APIを使ってサービスを構築
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
service = build('sheets', 'v4', credentials=credentials)

# ユーザーの状態を管理するための辞書
user_data = {}

# 全角文字を半角に変換する関数
def to_half_width(text):
    return text.translate(str.maketrans({
        '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
        '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
        '／': '/', '－': '-', '：': ':', '（': '(', '）': ')',
        '。': '.', '、': ','
    }))

# クリーンな入力を得るための関数
def clean_input(user_input):
    half_width = to_half_width(user_input)
    return re.sub(r'[^0-9/-]', '', half_width)

# Google Sheetsに売上データを追加する関数
def add_sales_data_to_google_sheets(date, payer, customer_count, sales):
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
    user_message = event.message.text

    if user_id not in user_data:
        user_data[user_id] = {'step': 0, 'sales_info': []}

    current_step = user_data[user_id]['step']

    if current_step == 0:
        if user_message == "売り上げ報告":
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="営業日を入力してください（例: 2025/01/01）")
            )
            user_data[user_id]['step'] = 1
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="「売り上げ報告」と入力してください。")
            )
    
    elif current_step == 1:
        user_data[user_id]['sales_info'].append({'date': user_message})
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="伝票の枚数を入力してください。")
        )
        user_data[user_id]['step'] = 2
    
    elif current_step == 2:
        cleaned_message = clean_input(user_message)

        try:
            receipt_count = int(cleaned_message)
            user_data[user_id]['sales_info'][0]['receipt_count'] = receipt_count
            user_data[user_id]['sales_info'][0]['transactions'] = []
            user_data[user_id]['current_receipt'] = 0  # 現在の伝票のインデックスを初期化
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="支払い者の名前を入力してください。")
            )
            user_data[user_id]['step'] = 3
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="伝票の枚数は数字で入力してください。数字以外の値は無効です。")
            )
    
    elif current_step == 3:
        current_receipt_index = user_data[user_id].get('current_receipt', 0)
        
        # 支払い者の名前を取得
        payer = user_message
        
        # 伝票に支払い者の名前を追加
        user_data[user_id]['sales_info'][0]['transactions'].append({'payer': payer, 'customer_count': 0, 'sales': 0})
        user_data[user_id]['current_receipt'] += 1  # 次の伝票に移動

        if user_data[user_id]['current_receipt'] < user_data[user_id]['sales_info'][0]['receipt_count']:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"{user_data[user_id]['current_receipt']}枚目の伝票の人数を入力してください。")
            )
            user_data[user_id]['step'] = 4
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="全ての伝票についての報告が終了しました。")
            )
            user_data[user_id]['step'] = 0

    elif current_step == 4:
        cleaned_message = clean_input(user_message)

        try:
            customer_count = int(cleaned_message)
            current_receipt_index = user_data[user_id]['current_receipt'] - 1  # 現在の伝票のインデックス
            user_data[user_id]['sales_info'][0]['transactions'][current_receipt_index]['customer_count'] = customer_count

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"伝票{user_data[user_id]['current_receipt']}の売上を入力してください。")
            )
            user_data[user_id]['step'] = 5
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="伝票の人数は数字で入力してください。有効な数字を入力してください。")
            )

    elif current_step == 5:
        sales = user_message
        current_receipt_index = user_data[user_id]['current_receipt'] - 1
        user_data[user_id]['sales_info'][0]['transactions'][current_receipt_index]['sales'] = sales

        if user_data[user_id]['current_receipt'] < user_data[user_id]['sales_info'][0]['receipt_count']:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"伝票{user_data[user_id]['current_receipt']}の支払い者の名前を入力してください。")
            )
            user_data[user_id]['step'] = 3
        else:
            # すべての伝票情報をGoogle Sheetsに追加
            try:
                for transaction in user_data[user_id]['sales_info'][0]['transactions']:
                    add_sales_data_to_google_sheets(
                        user_data[user_id]['sales_info'][0]['date'],
                        transaction['payer'],
                        transaction['customer_count'],
                        transaction['sales']
                    )
                total_sales = sum(int(transaction['sales']) for transaction in user_data[user_id]['sales_info'][0]['transactions'])
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"本日の売上は {total_sales} 円でした。\n報告を終了するには「終了」、新しい伝票を追加するには「新規」と入力してください。")
                )
                user_data[user_id]['step'] = 0
            except Exception as e:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="データの登録中にエラーが発生しました。再試行してください。")
                )

    elif user_message == "終了":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="報告を終了しました。")
        )
        del user_data[user_id]

    elif user_message == "新規":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="新しい伝票の報告を開始します...")
        )
        user_data[user_id]['step'] = 0

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="入力が不明です。正しい指示を入力してください。")
        )

@app.route('/', methods=['GET'])
def home():
    return "Welcome to the Line Bot!"

@app.route('/favicon.ico')
def favicon():
    return '', 204

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)