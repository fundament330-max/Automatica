import os
import re
import requests
import gspread
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from oauth2client.service_account import ServiceAccountCredentials

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = os.environ.get("BITRIX_WEBHOOK")
FOLDER_ID = "131672" 
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1znszruyFQu9AuXpe196rtBfLYB86MfFbnhZpSMsxgxE/edit"
# ==============================================

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

def extract_text_from_file(filename):
    text = ""
    try:
        if filename.lower().endswith('.pdf'):
            images = convert_from_path(filename)
            for img in images:
                text += pytesseract.image_to_string(img, lang='rus+eng') + "\n"
        elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            text = pytesseract.image_to_string(Image.open(filename), lang='rus+eng')
    except Exception as e:
        print(f"Ошибка OCR для {filename}: {e}")
    return text

def parse_passport_text(text, filename):
    # Ищем дату в тексте или в названии файла
    date_match = re.search(r'\b(3[01]|[12][0-9]|0[1-9])\.(1[0-2]|0[1-9])\.(\d{4})\b|\b(\d{4})\.(0[1-9]|1[0-2])\.(3[01]|[12][0-9]|0[1-9])\b', text)
    date_str = date_match.group(0) if date_match else ""
    
    if not date_str:
        file_date_match = re.search(r'(\d{4}\.\d{2}\.\d{2})', filename)
        if file_date_match:
            date_str = file_date_match.group(1)

    # Ищем номер паспорта/сертификата
    passport_match = re.search(r'(?:паспорт[а-я]*|сертификат[а-я]*)\s*(?:№|с|качества)?[:\s]*([А-Яа-яA-Za-z0-9\-\/]+)', text, re.IGNORECASE)
    passport_no = passport_match.group(1) if passport_match else ""

    # Ищем количество
    qty_match = re.search(r'(?:кол-во|количество|объем|масса)[:\s]*([0-9\.,]+\s*(?:м3|т|кг|шт|п\.м\.|мг))', text, re.IGNORECASE)
    quantity = qty_match.group(1) if qty_match else ""

    # Наименование материала из имени файла (или очищенное)
    clean_name = re.sub(r'\.(pdf|jpg|png|jpeg)$', '', filename, flags=re.IGNORECASE)
    clean_name = re.sub(r'^\d{4}\.\d{2}\.\d{2}\s*', '', clean_name)
    material_name = clean_name

    # Поставщик
    supplier = ""
    lines = text.split('\n')
    for line in lines:
        if any(w in line.lower() for w in ['изготовитель', 'поставщик', 'завод', 'ооо', 'ао', 'пао']):
            if len(line.strip()) > 5:
                supplier = line.strip()
                break

    return {
        "date": date_str,
        "material": material_name,
        "supplier": supplier,
        "quantity": quantity,
        "passport_no": passport_no
    }

def main():
    print("Подключение к таблице...")
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) 
    
    print("Запрос файлов из Битрикса...")
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME", "")
        file_url = file_info.get("DETAIL_URL", "")
        download_url = file_info.get("DOWNLOAD_URL", "")
        
        if not download_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        print(f"\nОбработка файла: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}: {e}")
            continue
            
        raw_text = extract_text_from_file(filename)
        data = parse_passport_text(raw_text, filename)
        
        next_row = len(sheet.col_values(1)) + 1
        
        row_data = [[
            next_row - 1,
            data["date"],
            data["material"],
            data["supplier"],
            data["quantity"],
            data["passport_no"],
            "", "", "", "",
            file_url
        ]]
        
        print(f"Запись -> Дата: {data['date']} | Материал: {data['material']} | Паспорт: {data['passport_no']}")
        sheet.update(values=row_data, range_name=f'A{next_row}:K{next_row}')
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Реестр собран.")

if __name__ == '__main__':
    main()
