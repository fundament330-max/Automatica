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
BITRIX_WEBHOOK = os.environ.get("BITRIX_WEBHOOK")
FOLDER_ID = "131672" # Твой ID папки в Битрикс24
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GOOGLE_SHEET_NAME = "Реестр паспортов" # Так должна называться твоя таблица!
# ==============================================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def init_google_sheets():
    with open("google_creds.json", "w") as f:
        f.write(GOOGLE_CREDS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    client = gspread.authorize(creds)
    return client.open(GOOGLE_SHEET_NAME).sheet1

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
    Извлеки данные из паспорта качества. Ответь ТОЛЬКО в формате JSON.
    Если данных нет, ставь пустую строку "".
    {
      "date": "Дата документа ДД.ММ.ГГГГ",
      "material": "Полное наименование материала",
      "supplier": "Организация поставщик",
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
    existing_links = sheet.col_values(11) # Столбец K
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info["NAME"]
        file_url = file_info["DETAIL_URL"]
        download_url = file_info["DOWNLOAD_URL"]
        
        if file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png')):
            continue
            
        print(f"Обработка {filename}...")
        with open(filename, 'wb') as f:
            f.write(requests.get(download_url).content)
            
        raw_text = extract_text(filename)
        parsed_data = parse_with_gemini(raw_text)
        
        next_num = len(sheet.col_values(1))
        new_row = [
            next_num, parsed_data.get("date", ""), parsed_data.get("material", ""), 
            parsed_data.get("supplier", ""), parsed_data.get("quantity", ""), 
            parsed_data.get("passport_no", ""), "", "", "", "", file_url
        ]
        
        sheet.append_row(new_row)
        os.remove(filename)

if __name__ == '__main__':
    main()
