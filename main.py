import os
import json
import requests
import gspread
import re
import time
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = "https://nefteresurs.bitrix24.ru/rest/752/yc6s3l7fghnba6h0/"
FOLDER_ID = "131672" 
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1znszruyFQu9AuXpe196rtBfLYB86MfFbnhZpSMsxgxE/edit"
# ==============================================

genai.configure(api_key=GEMINI_API_KEY)

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

def parse_pdf_with_gemini(filename):
    prompt = """
    Найди в этом паспорте качества 3 параметра:
    - "supplier" (поставщик/изготовитель)
    - "quantity" (количество/объем и ед. изм)
    - "passport_no" (номер паспорта/документа)
    
    Верни только эти 3 ключа. Если чего-то нет, пиши пустую строку "".
    """
    try:
        uploaded_file = genai.upload_file(path=filename)
        time.sleep(3) # Даем нейросети время на чтение файла
        
        # Жестко заставляем модель отвечать только в JSON
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content([prompt, uploaded_file])
        genai.delete_file(uploaded_file.name)
        
        return json.loads(response.text)
    except Exception as e:
        print(f"Ошибка ИИ для {filename}: {e}")
        return {}

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
            
        print(f"\nСкачиваем: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}")
            continue
            
        # Нейросеть ищет только 3 сложных параметра
        ai_data = parse_pdf_with_gemini(filename)
        
        # А дату и материал берем из названия файла (работает на 100%)
        clean_name = re.sub(r'\.(pdf|jpg|png|jpeg)$', '', filename, flags=re.IGNORECASE)
        date_str = ""
        material_name = clean_name
        
        match = re.match(r"^(\d{4}\.\d{2}\.\d{2})\s*(.*)", clean_name)
        if match:
            date_str = match.group(1)
            material_name = match.group(2)
        
        next_row = len(sheet.col_values(1)) + 1
        
        row_data = [[
            next_row - 1,
            date_str,
            material_name,
            ai_data.get("supplier", ""),
            ai_data.get("quantity", ""),
            ai_data.get("passport_no", ""),
            "", "", "", "",
            file_url
        ]]
        
        print(f"Запись: {material_name} | Поставщик: {ai_data.get('supplier')} | Кол-во: {ai_data.get('quantity')}")
        sheet.update(f'A{next_row}:K{next_row}', row_data)
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Все файлы обработаны.")

if __name__ == '__main__':
    main()
