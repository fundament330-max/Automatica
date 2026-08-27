import os
import json
import requests
import gspread
import time
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = "https://nefteresurs.bitrix24.ru/rest/752/yc6s3l7fghnba6h0/"
ROOT_FOLDER_ID = "131672" # Корневая папка ПТО
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

def get_folder_id_by_path(webhook, root_id):
    """Автоматически ищет нужную папку «ЦОД А» по иерархии"""
    target_path = ["5. ПАСПОРТА", "Конструкции железобетонные", "Бетон", "ЦОД А"]
    current_id = root_id
    
    for folder_name in target_path:
        url = f"{webhook}disk.folder.getchildren"
        response = requests.post(url, json={"id": current_id})
        items = response.json().get("result", [])
        
        found = False
        for item in items:
            # Ищем совпадение по имени (без учета регистра и пробелов)
            if item.get("NAME", "").strip().lower() == folder_name.lower():
                current_id = item.get("ID")
                found = True
                break
        if not found:
            print(f"Не удалось найти папку: {folder_name}. Берем текущую корневую.")
            break
            
    print(f"🎯 Итоговый ID найденной папки: {current_id}")
    return current_id

def parse_pdf_with_gemini(filename):
    prompt = """
    Ты профессиональный инженер ПТО. Проанализируй этот документ (паспорт качества или сертификат).
    Извлеки и верни строго JSON объект с полями:
    - "date": дата документа (ДД.ММ.ГГГГ или ГГГГ.ММ.ДД).
    - "material": точное наименование материала или изделия.
    - "supplier": завод-изготовитель или поставщик (только название организации).
    - "quantity": ТОЛЬКО количественное значение с единицей измерения (например: "50 шт", "12.5 м3", "300 т"). Только цифры и единица, без лишних слов.
    - "passport_no": ТОЛЬКО номер паспорта или сертификата (конкретная цифра или буквенно-цифровой индекс, например "4278", "№ 54"). Никаких слов вроде "Соответствия".

    Если параметра нет, оставь "". Ответ строго в формате JSON.
    """
    try:
        print(f"Загружаем {filename} для анализа ИИ...")
        uploaded_file = genai.upload_file(path=filename)
        
        while True:
            file_info = genai.get_file(uploaded_file.name)
            if file_info.state.name == 'PROCESSING':
                time.sleep(2)
            elif file_info.state.name == 'FAILED':
                return {}
            else:
                break

        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content([prompt, file_info])
        genai.delete_file(uploaded_file.name)
        
        return json.loads(response.text)
    except Exception as e:
        print(f"Ошибка ИИ для {filename}: {e}")
        return {}

def main():
    print("Подключение к таблице...")
    sheet = init_google_sheets()
    existing_links = sheet.col_values(11) 
    
    print("Поиск нужной папки в Битриксе...")
    target_folder_id = get_folder_id_by_path(BITRIX_WEBHOOK, ROOT_FOLDER_ID)
    
    url = f"{BITRIX_WEBHOOK}disk.folder.getchildren"
    files = requests.post(url, json={"id": target_folder_id}).json().get("result", [])
    
    for file_info in files:
        filename = file_info.get("NAME", "")
        file_url = file_info.get("DETAIL_URL", "")
        download_url = file_info.get("DOWNLOAD_URL", "")
        
        if not download_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        print(f"\nСкачиваем: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}: {e}")
            continue
            
        ai_data = parse_pdf_with_gemini(filename)
        
        material_name = ai_data.get("material")
        if not material_name:
            material_name = filename
            
        next_row = len(sheet.col_values(1)) + 1
        
        row_data = [[
            next_row - 1,
            ai_data.get("date", ""),
            material_name,
            ai_data.get("supplier", ""),
            ai_data.get("quantity", ""),
            ai_data.get("passport_no", ""),
            "", "", "", "",
            file_url
        ]]
        
        print(f"Запись -> Кол-во: {ai_data.get('quantity')} | Паспорт: {ai_data.get('passport_no')}")
        sheet.update(values=row_data, range_name=f'A{next_row}:K{next_row}')
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Файлы из папки ЦОД А обработаны.")

if __name__ == '__main__':
    main()
