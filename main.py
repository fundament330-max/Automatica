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

def parse_with_gemini(text, filename):
    prompt = f"""
    Ты опытный инженер ПТО. Проанализируй текст паспорта качества и извлеки данные.
    Верни строго JSON объект с такими ключами:
    - "date" (дата документа)
    - "material" (наименование материала)
    - "supplier" (поставщик)
    - "quantity" (количество)
    - "passport_no" (номер паспорта)
    
    Если чего-то нет, укажи пустую строку "".
    Имя файла для справки: {filename}
    
    Текст документа:
    {text}
    """
    try:
        response = model.generate_content(prompt)
        text_res = response.text.replace("```json", "").replace("```", "").strip()
        start = text_res.find("{")
        end = text_res.rfind("}") + 1
        if start != -1 and end != 0:
            return json.loads(text_res[start:end])
    except Exception as e:
        print(f"Ошибка Gemini парсинга: {e}")
    
    return {"date": "", "material": filename, "supplier": "", "quantity": "", "passport_no": ""}

def main():
    print("Подключение к таблице...")
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) 
    
    print("Запрос файлов из Битрикса...")
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME")
        file_url = file_info.get("DETAIL_URL")
        download_url = file_info.get("DOWNLOAD_URL")
        
        if not download_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        print(f"Скачиваем: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}: {e}")
            continue
            
        raw_text = extract_text(filename)
        parsed_data = parse_with_gemini(raw_text, filename)
        
        # Жестко вычисляем номер следующей строки ТОЛЬКО по колонке А
        next_row = len(sheet.col_values(1)) + 1
        material_name = parsed_data.get("material") or filename
        
        # Собираем данные в виде массива внутри массива (требование метода update)
        row_data = [[
            next_row - 1,
            parsed_data.get("date", ""),
            material_name,
            parsed_data.get("supplier", ""),
            parsed_data.get("quantity", ""),
            parsed_data.get("passport_no", ""),
            "", "", "", "",
            file_url
        ]]
        
        print(f"Записываем в координаты A{next_row}:K{next_row} -> {material_name}")
        # Жестко бьем в конкретные координаты ячеек
        sheet.update(f'A{next_row}:K{next_row}', row_data)
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("Готово! Все файлы обработаны.")

if __name__ == '__main__':
    main()
