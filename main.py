import os
import json
import requests
import gspread
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
    Ты опытный инженер ПТО. Внимательно изучи этот документ (паспорт качества/сертификат).
    Извлеки из текста внутри документа следующие данные:
    - "date": дата выдачи документа (в формате ДД.ММ.ГГГГ или ГГГГ.ММ.ДД)
    - "material": наименование строительного материала или изделия
    - "supplier": наименование поставщика или завода-изготовителя
    - "quantity": количество/объем и единицы измерения (например, 50 м3, 120 шт)
    - "passport_no": номер паспорта или сертификата качества
    
    Верни результат СТРОГО в формате JSON с этими 5 ключами. Если какого-то параметра нет в тексте, оставь пустую строку "". Не пиши ничего, кроме JSON.
    """
    try:
        print(f"Загружаем {filename} в нейросеть...")
        uploaded_file = genai.upload_file(path=filename)
        
        # Ждем, пока Гугл обработает файл
        while True:
            file_info = genai.get_file(uploaded_file.name)
            if file_info.state.name == 'PROCESSING':
                print("Ждем обработку файла Гуглом...")
                time.sleep(2)
            elif file_info.state.name == 'FAILED':
                print("Ошибка обработки файла на серверах Гугла.")
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
    
    print("Запрос файлов из Битрикса...")
    files = get_bitrix_files()
    
    for file_info in files:
        filename = file_info.get("NAME", "")
        file_url = file_info.get("DETAIL_URL", "")
        download_url = file_info.get("DOWNLOAD_URL", "")
        
        if not download_url or file_url in existing_links or not filename.lower().endswith(('.pdf', '.jpg', '.png', '.jpeg')):
            continue
            
        try:
            with open(filename, 'wb') as f:
                f.write(requests.get(download_url).content)
        except Exception as e:
            print(f"Не удалось скачать {filename}")
            continue
            
        # Достаем ВСЕ данные строго изнутри файла через нейросеть
        ai_data = parse_pdf_with_gemini(filename)
        
        # Страховка: если нейросеть совсем не смогла прочитать материал, подставим имя файла
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
        
        print(f"Запись: {material_name} | Дата: {ai_data.get('date')} | Поставщик: {ai_data.get('supplier')} | Кол-во: {ai_data.get('quantity')}")
        
        sheet.update(values=row_data, range_name=f'A{next_row}:K{next_row}')
        
        if os.path.exists(filename):
            os.remove(filename)
            
    print("\nГотово! Все данные извлечены из документов.")

if __name__ == '__main__':
    main()
