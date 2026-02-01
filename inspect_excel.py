
import openpyxl

def inspect_excel():
    try:
        wb = openpyxl.load_workbook('kommunlankod-2026.xlsx')
        sheet = wb.active
        print(f"Sheet Name: {sheet.title}")
        
        # Read first 5 rows
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            print(f"Row {i}: {row}")
            if i >= 5:
                break
    except Exception as e:
        print(f"Error reading excel: {e}")

if __name__ == "__main__":
    inspect_excel()
