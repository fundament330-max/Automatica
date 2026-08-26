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
        print(f"Ошибка OCR при чтении {filename}: {e}")
    return text

def parse_with_gemini(text):
    prompt = """
    Ты — помощник инженера ПТО. Извлеки данные из текста паспорта качества на строительный материал.
    Ответь ТОЛЬКО в формате JSON. Не пиши никаких пояснений.
    Если данных нет, ставь пустую строку "".
    
    Структура JSON:
    {
      "date": "Дата документа в формате ДД.ММ.ГГГГ",
      "material": "Полное наименование материала",
      "supplier": "Название организации поставщика",
      "quantity": "Количество и единицы измерения",
      "passport_no": "Номер паспорта или сертификата"
    }
    
    Текст:
    """
    try:
        response = model.generate_content(prompt + text)
        result = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(result)
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        return {"date": "", "material": "", "supplier": "", "quantity": "", "passport_no": ""}

def main():
    print("Подключение к Гугл Таблице...")
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) # Столбец K со ссылками
    
    print("Получение файлов из Битрикс24...")
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME", "Без_имени")
        file_url = file_info.get("DETAIL_URL", "")
        download_url = file_info.get("DOWNLOAD_URL")
        
        if not download_url:
            continue
            
        if file_url in existing_links:
            print(f"Пропуск {filename} (уже в реестре)")
            continue
            
        if not filename.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
            continue
            
        print(f"\nОбработка файла: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Ошибка скачивания {filename}: {e}")
            continue
            
        raw_text = extract_text(filename)
        if not raw_text.strip():
            print(f"Текст не распознан для {filename}")
            if os.path.exists(filename):
                os.remove(filename)
            continue
            
        print("Распознавание данных через Gemini...")
        parsed_data = parse_with_gemini(raw_text)
        
        # Вычисляем следующий номер по порядку
        next_num = len(sheet.col_values(1)) 
        
        # Формируем строку строго по колонкам таблицы:
        # A: №п/п, B: дата, C: материал, D: поставщик, E: кол-во, F: № паспорта, G-J: пусто, K: ссылка
        new_row = [
            next_num, 
            parsed_data.get("date", ""), 
            parsed_data.get("material", ""), 
            parsed_data.get("supplier", ""), 
            parsed_data.get("quantity", ""), 
            parsed_data.get("passport_no", ""), 
            "", "", "", "", 
            file_url
        ]
        
        sheet.append_row(new_row)
        print(f"Успешно записано в таблицу: {parsed_data.get('material')}")
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Все файлы обработаны.")

if __name__ == '__main__':
    main()
