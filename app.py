from flask import Flask, request, abort
import requests
import openpyxl
import os
from msal import ConfidentialClientApplication
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import datetime

app = Flask(__name__)

# LINE Botの設定
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')  # 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')  # 環境変数から取得
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Azureの設定
CLIENT_ID = os.getenv('CLIENT_ID')  # 環境変数から取得
CLIENT_SECRET = os.getenv('CLIENT_SECRET')  # 環境変数から取得
TENANT_ID = os.getenv('TENANT_ID')  # 環境変数から取得
GRAPH_SCOPE = ['https://graph.microsoft.com/Files.ReadWrite.All']

# Excelファイル名
EXCEL_FILE_NAME = 'sales_report.xlsx'

# アクセストークンを取得する関数
def get_access_token():
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    return result.get('access_token')

# Excelファイルに売上データを追加する関数
def add_sales_data_to_excel(sales_amount):
    file_path = EXCEL_FILE_NAME

    if not os.path.exists(file_path):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(['日付', '売上'])
    else:
        workbook = openpyxl.load_workbook(file_path)
        sheet = workbook.active

    # 売上データを追加
    sheet.append([str(datetime.datetime.now()), sales_amount])
    workbook.save(file_path)

# OneDriveにExcelファイルをアップロードする関数
def upload_file_to_onedrive():
    access_token = get_access_token()
    with open(EXCEL_FILE_NAME, 'rb') as file:
        headers = {'Authorization': f'Bearer {access_token}'}
        upload_url = f'https://graph.microsoft.com/v1.0/me/drive/root:/{EXCEL_FILE_NAME}:/content'
        response = requests.put(upload_url, headers=headers, data=file)
        return response.status_code == 201  # 成功した場合はTrueを返す

# Webhookエンドポイント
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# メッセージを処理する
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    
    # メッセージが「売上:金額」の形式の場合
    if user_message.startswith("売上:"):
        sales_amount = user_message.replace("売上:", "").strip()
        
        # Excelに売上データを追加
        add_sales_data_to_excel(sales_amount)
        
        # OneDriveにアップロード
        if upload_file_to_onedrive():
            reply_message = f"売上データ「{sales_amount}円」を保存しました。"
        else:
            reply_message = "OneDriveへのアップロードに失敗しました。"
    else:
        reply_message = "売上データを報告するには「売上:金額」と入力してください。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_message)
    )

# ルートURLに対するハンドラを追加
@app.route('/', methods=['GET'])
def home():
    return "Welcome to the Line Bot!"

# favicon.icoリクエストに応じる
@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content

if __name__ == "__main__":
    # app.run(host='0.0.0.0', port=8000)  # Renderでは特にポートを指定する必要はありません
    pass  # 実際の処理がなくてもパスを置くことができます
