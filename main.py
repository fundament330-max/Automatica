import os
import requests
import gspread
import re
from oauth2client.service_account import ServiceAccountCredentials

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = "https://nefteresurs.bitrix24.ru/rest/752/yc6s3l7fghnba6h0/"
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

def main():
    print("Подключение к таблице...")
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) 
    
    print("Запрос файлов из Битрикса...")
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME", "")
        file_url = file_info.get("DETAIL_URL", "")
        
        # Пропускаем, если файл уже есть в таблице или это не картинка/pdf
        if not file_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        clean_name = re.sub(r'\.(pdf|jpg|png|jpeg)$', '', filename, flags=re.IGNORECASE)
        date_str = ""
        material_name = clean_name
        
        # Ищем дату (ГГГГ.ММ.ДД) и название в имени файла
        match = re.match(r"^(\d{4}\.\d{2}\.\d{2})\s*(.*)", clean_name)
        if match:
            date_str = match.group(1)
            material_name = match.group(2)
        
        next_row = len(sheet.col_values(1)) + 1
        
        row_data = [[
            next_row - 1,
            date_str,
            material_name,
            "", # Поставщик - оставим для ручного ввода
            "", # Кол-во
            "", # № паспорта
            "", "", "", "",
            file_url
        ]]
        
        print(f"Запись: {material_name}")
        sheet.update(f'A{next_row}:K{next_row}', row_data)
            
    print("\nГотово! Реестр собран.")

if __name__ == '__main__':
    main()
