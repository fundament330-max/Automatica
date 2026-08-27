import os
import json
import requests
import gspread
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

def parse_pdf_with_gemini(filename):
    prompt = """
    Ты опытный инженер ПТО. Изучи этот документ (паспорт качества/сертификат).
    Извлеки из него данные и верни строго JSON объект с ключами:
    - "date" (дата документа)
    - "material" (наименование материала из документа)
    - "supplier" (поставщик или изготовитель)
    - "quantity" (объем/количество и ед. изм)
    - "passport_no" (номер паспорта/сертификата)
    
    Если каких-то данных нет на скане, укажи пустую строку "".
    Отвечай ТОЛЬКО форматом JSON, без лишнего текста.
    """
    try:
        uploaded_file = genai.upload_file(path=filename)
        response = model.generate_content([prompt, uploaded_file])
        genai.delete_file(uploaded_file.name)
        
        text_res = response.text.replace("```json", "").replace("```", "").strip()
        start = text_res.find("{")
        end = text_res.rfind("}") + 1
        if start != -1 and end != 0:
            return json.loads(text_res[start:end])
    except Exception as e:
        print(f"Ошибка при анализе файла {filename}: {e}")
        
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
            
        print(f"\nСкачиваем и анализируем: {filename}")
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}")
            continue
            
        parsed_data = parse_pdf_with_gemini(filename)
        
        next_row = len(sheet.col_values(1)) + 1
        
        material_name = parsed_data.get("material")
        if not material_name:
            material_name = filename
            
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
        
        print(f"Записываем данные -> Поставщик: {parsed_data.get('supplier', 'Нет')}, Материал: {material_name}")
        sheet.update(f'A{next_row}:K{next_row}', row_data)
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Все файлы обработаны.")

if __name__ == '__main__':
    main()
