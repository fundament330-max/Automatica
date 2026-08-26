import os
import json
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = "https://nefteresurs.bitrix24.ru/rest/752/yc6s3l7fghnba6h0/"
FOLDER_ID = "131672" 
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1znszruyFQu9AuXpe196rtBfLYB86MfFbnhZpSMsxgxE/edit"
# ==============================================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def init_google_sheets():
    with open("google_creds.json", "w") as f:
        f.write(GOOGLE_CREDS_JSON)
        
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    client = gspread.authorize(creds)
    return client.open_by_url(GOOGLE_SHEET_URL).sheet1

def get_bitrix_files():
    url = f"{BITRIX_WEBHOOK}disk.folder.getchildren"
    response = requests.post(url, json={"id": FOLDER_ID})
    return response.json().get("result", [])

def extract_text(filename):
    text = ""
    try:
        if filename.lower().endswith('.pdf'):
            images = convert_from_path(filename)
            for img in images:
                text += pytesseract.image_to_string(img, lang='rus')
        elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            text = pytesseract.image_to_string(Image.open(filename), lang='rus')
    except Exception as e:
        print(f"Ошибка OCR: {e}")
    return text

def parse_with_gemini(text):
    prompt = """
    Извлеки данные из текста паспорта качества на строительный материал.
    Ответь ТОЛЬКО в формате JSON. Без лишнего текста.
    Если данных нет, ставь пустую строку "".
    {
      "date": "Дата документа в формате ДД.ММ.ГГГГ",
      "material": "Наименование материала",
      "supplier": "Поставщик",
      "quantity": "Количество и ед. изм",
      "passport_no": "Номер паспорта"
    }
    Текст: """
    try:
        response = model.generate_content(prompt + text)
        result = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(result)
    except:
        return {"date": "", "material": "", "supplier": "", "quantity": "", "passport_no": ""}

def main():
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) 
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME")
        file_url = file_info.get("DETAIL_URL")
        download_url = file_info.get("DOWNLOAD_URL")
        
        if not download_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        with open(filename, 'wb') as f:
            f.write(requests.get(download_url).content)
            
        raw_text = extract_text(filename)
        parsed_data = parse_with_gemini(raw_text)
        
        next_num = len(sheet.col_values(1))
        
        # Собираем всю строку целиком от A до K и отправляем одним пакетом
        row_data = [
            next_num,
            parsed_data.get("date", ""),
            parsed_data.get("material", ""),
            parsed_data.get("supplier", ""),
            parsed_data.get("quantity", ""),
            parsed_data.get("passport_no", ""),
            "", "", "", "",
            file_url
        ]
        
        sheet.append_row(row_data)
        os.remove(filename)

if __name__ == '__main__':
    main()
