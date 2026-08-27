import os
import json
import requests
import gspread
import base64
from oauth2client.service_account import ServiceAccountCredentials

# ================= НАСТРОЙКИ =================
BITRIX_WEBHOOK = "https://nefteresurs.bitrix24.ru/rest/752/yc6s3l7fghnba6h0/"
ROOT_FOLDER_ID = "131672" 
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1znszruyFQu9AuXpe196rtBfLYB86MfFbnhZpSMsxgxE/edit"
# ==============================================

def init_google_sheets():
    with open("google_creds.json", "w") as f:
        f.write(GOOGLE_CREDS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    client = gspread.authorize(creds)
    return client.open_by_url(GOOGLE_SHEET_URL).sheet1

def get_folder_id_by_path(webhook, root_id):
    # ИЩЕМ СТРОГО ПО НАЗВАНИЮ, чтобы не залезть в "Паспорта с ошибками"
    target_path = ["5. ПАСПОРТА", "1. Конструкции железобетонные", "Бетон", "ЦОД А"]
    current_id = root_id
    
    for folder_name in target_path:
        url = f"{webhook}disk.folder.getchildren"
        response = requests.post(url, json={"id": current_id})
        items = response.json().get("result", [])
        
        found = False
        for item in items:
            if item.get("NAME", "").strip().lower() == folder_name.lower():
                current_id = item.get("ID")
                found = True
                print(f"📁 Нашли папку: {item.get('NAME')}")
                break
                
        if not found:
            print(f"❌ Не удалось найти точную папку: {folder_name}")
            break
            
    print(f"🎯 Итоговый ID папки для сканирования: {current_id}")
    return current_id

def parse_pdf_direct(filename):
    prompt = """
    Ты инженер ПТО. Проанализируй этот документ.
    Извлеки и верни строго JSON объект с полями:
    - "date": дата документа (ДД.ММ.ГГГГ или ГГГГ.ММ.ДД).
    - "material": точное наименование материала.
    - "supplier": завод-изготовитель или поставщик.
    - "quantity": ТОЛЬКО количественное значение с единицей измерения.
    - "passport_no": ТОЛЬКО номер паспорта или сертификата.
    Если параметра нет, оставь "". Ответ строго в формате JSON без разметки markdown.
    """
    try:
        with open(filename, "rb") as f:
            pdf_data = f.read()
            
        pdf_b64 = base64.b64encode(pdf_data).decode('utf-8')
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": pdf_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response_json = response.json()
        
        if response.status_code != 200:
            error_msg = response_json.get("error", {}).get("message", "Неизвестная ошибка API")
            return {}, f"Ошибка Google API: {error_msg}"
            
        # Достаем текст из ответа
        text_result = response_json["candidates"][0]["content"]["parts"][0]["text"]
        text_result = text_result.replace("```json", "").replace("```", "").strip()
        
        return json.loads(text_result), None
    except Exception as e:
        return {}, str(e)

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
        except Exception:
            continue
            
        ai_data, error_msg = parse_pdf_direct(filename)
        
        if error_msg:
            material_name = f"🛑 ОШИБКА: {error_msg}"
        else:
            material_name = ai_data.get("material", filename)
            
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

if __name__ == '__main__':
    main()
