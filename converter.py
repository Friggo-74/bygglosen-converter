import xml.etree.ElementTree as ET
import csv
import io
from collections import defaultdict

def clean_personnr(pnr):
    """Tar bort bindestreck för att matcha XML-formatet."""
    if not pnr:
        return ""
    return pnr.replace("-", "").strip()

def pad_lankod(kod):
    """Ser till att länskoden alltid är 4 siffror (t.ex. 662 -> 0662)."""
    if not kod:
        return None
    return kod.strip().zfill(4)

import openpyxl
import os

def load_lankod_map(excel_path='kommunlankod-2026.xlsx'):
    """Laddar en map från Kod -> Namn från Excel-filen."""
    lankod_map = {}
    if not os.path.exists(excel_path):
        return lankod_map # Returnera tom om filen saknas
        
    try:
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        sheet = wb.active
        # Antar strukturen: Kolumn A = Kod, Kolumn B = Namn
        # Hoppar över första raderna (header) om de inte är koder
        for row in sheet.iter_rows(values_only=True):
            if not row or len(row) < 2:
                continue
            
            kod, namn = row[0], row[1]
            
            # Konvertera till sträng och validera lite lätt
            if kod:
                kod_str = str(kod).strip().zfill(4) # Säkra formatet
                namn_str = str(namn).strip()
                # En enkel koll att koden ser ut som en sifferkod
                if kod_str.isdigit():
                   lankod_map[kod_str] = namn_str
    except Exception as e:
        print(f"Varning: Kunde inte läsa excel-filen: {e}")
        
    return lankod_map

def convert_bygglosen_data(xml_file_streams, csv_file_stream=None, default_lankod="1293"):
    """
    Konverterar data från XML och CSV streams.
    xml_file_streams: list of file-like objects (binary or text depending on parsing needs)
    csv_file_stream: file-like object (text mode preferable) - OPTIONAL
    
    Om csv_file_stream är None, används länkoderna som redan finns i XML-filerna.
    """
    
    # Ladda upp länskods-mappning en gång
    # I en riktig prod-app borde detta cachas, men här är det ok
    lankod_namn_map = load_lankod_map()
    
    # 1. Läs in CSV-filen till en dictionary (om den finns)
    # Mappar Personnummer -> LänKod
    pnr_to_lankod = {}
    
    # Endast processa CSV om den faktiskt skickades med
    if csv_file_stream is not None:
        # Flask skickar ofta BytesIO, vi behöver text för csv module
        # Vi försöker först med utf-8-sig, men faller tillbaka på iso-8859-1 (vanligt för svenska Excel-filer)
        encodings_to_try = ['utf-8-sig', 'iso-8859-1', 'cp1252']
        csv_rows = []
        
        # Spara positionen så vi kan spola tillbaka om första försöket misslyckas
        start_pos = csv_file_stream.tell()
        
        success = False
        for encoding in encodings_to_try:
            try:
                csv_file_stream.seek(start_pos)
                wrapper = io.TextIOWrapper(csv_file_stream, encoding=encoding, newline='')
                # Läs allt till en lista för att faktiskt trigga en eventuell decode error direkt
                data = wrapper.read()
                
                # Om vi lyckas läsa, skapa en ny reader från strängen
                wrapper.detach() # Viktigt: stäng inte underliggande bytes-stream
                
                # Använd io.StringIO för att mata csv.DictReader
                reader = csv.DictReader(io.StringIO(data), delimiter=';')
                csv_rows = list(reader) # Spara rader
                success = True
                break
            except UnicodeDecodeError:
                # Om wrapper craschar detachar vi ändå för att inte stänga streamen i finally (om vi hade haft en)
                if 'wrapper' in locals():
                    try:
                        wrapper.detach()
                    except Exception:
                        pass
                continue
                
        if not success:
             raise ValueError("Kunde inte läsa CSV-filen. Kontrollera att den är sparad som UTF-8 eller ISO-8859-1.")

        for row in csv_rows:
            # Hantera fall där CSV kanske har andra kolumnnamn eller whitespace
            pnr_raw = row.get('Personnr', '')
            lankod_raw = row.get('Län och kommun', '')
            
            pnr = clean_personnr(pnr_raw)
            lankod = pad_lankod(lankod_raw)
            
            if pnr and lankod:
                pnr_to_lankod[pnr] = lankod

    # 2. Parsa XML-filerna (Konteks filer)
    # Vi itererar över alla filer och samlar personer
    
    all_persons_collected = []
    header_data = None
    
    # Om argumentet inte är en lista, gör det till en lista (för bakåtkompatibilitet)
    if not isinstance(xml_file_streams, list):
        xml_file_streams = [xml_file_streams]

    for stream in xml_file_streams:
        try:
            tree = ET.parse(stream)
            root = tree.getroot()
            
            # Hitta Lonegranskning-gruppen
            original_group = root.find('Lonegranskning')
            if original_group is None:
                continue # Hoppa över trasig fil eller varna? Vi hoppar över här.

            # Spara header-värden bara från den FÖRSTA filen
            if header_data is None:
                header_data = {
                    'Organisationsnummer': original_group.findtext('Organisationsnummer'),
                    'Foretagsnamn': original_group.findtext('Foretagsnamn'),
                    'LoneperiodStartdatum': original_group.findtext('LoneperiodStartdatum'),
                    'LoneperiodSlutdatum': original_group.findtext('LoneperiodSlutdatum'),
                    'Avtalsomrade': original_group.findtext('Avtalsomrade'),
                    'Lonetyp': original_group.findtext('Lonetyp'),
                    'Postort': original_group.findtext('Postort') or ""
                }
            
            # Hämta länkod för denna fil (används som fallback om ingen CSV finns)
            file_lankod = original_group.findtext('LanOchKommun')
            
            # Hämta personer
            all_persons_container = original_group.find('Personer')
            if all_persons_container is not None:
                persons = all_persons_container.findall('Person')
                # Spara original länkod med varje person (som ett attribut för enkel åtkomst)
                for p in persons:
                    p.set('_original_lankod', file_lankod or '')
                all_persons_collected.extend(persons)
                
        except Exception as e:
            # Vi kan kasta vidare eller bara logga. Kasta är säkrast.
            raise ValueError(f"Kunde inte parsa en av XML-filerna: {e}")

    if not header_data:
        raise ValueError("Fel: Kunde inte hitta 'Lonegranskning' data i någon av XML-filerna.")

    # 3. Slå ihop personer med samma personnummer (Merge duplicates)
    # Definiera vilka fält som ska summeras
    fields_to_sum = [
        'ArbetadeTimmar', 'GrundlonPerTimma', 'UtbNivaPerTimma', 
        'UtbetaltOverskott', 'Lonesumma', 'OBTillagg', 
        'AvtalsenligManadslon', 'Overtidstimmar', 'Overtidstillagg', 
        'Rolltillagg', 'Aktivitetstillagg', 'Kompetenstillagg', 
        'Ansvarstillagg'
    ]
    
    merged_persons_map = {}
    
    for person in all_persons_collected:
        pnr = person.findtext('Personnummer')
        if not pnr:
            continue
            
        # Använd samma clean-funktion som för CSV-matchning för säkerhets skull
        clean_pnr = clean_personnr(pnr)
        
        if clean_pnr in merged_persons_map:
            existing_person = merged_persons_map[clean_pnr]
            
            # Summera fälten
            for field in fields_to_sum:
                # Hitta elementen
                elem_exist = existing_person.find(field)
                elem_new = person.find(field)
                
                # Om båda finns, addera
                if elem_exist is not None and elem_new is not None:
                    try:
                        val1 = float(elem_exist.text or 0)
                        val2 = float(elem_new.text or 0)
                        elem_exist.text = "{:.2f}".format(val1 + val2)
                    except ValueError:
                        pass # Om det inte är tal, strunta i det
                # Om fält saknas i "existing" men finns i "new", borde vi kopiera det?
                # För enkelhetens skull antar vi att strukturen är konstant (samma schema).
                # Om vi vill kopiera måste vi använda copy/append, men XML strukturen är strikt.
        else:
            merged_persons_map[clean_pnr] = person
            
    # Uppdatera listan med unika personer
    unique_persons = list(merged_persons_map.values())

    # 4. Gruppera personer baserat på CSV-datan (om den finns) eller befintlig XML-data
    # Dictionary structure: { "0581": [PersonElement1, PersonElement2], "1293": [...] }
    grouped_persons = defaultdict(list)
    
    for person in unique_persons:
        pnr_xml = person.findtext('Personnummer')
        clean_pnr = clean_personnr(pnr_xml)
        
        # Prioritetsordning:
        # 1. CSV-mappning (om tillgänglig)
        # 2. Befintlig LanOchKommun i XML-filen
        # 3. Default länkod
        if clean_pnr in pnr_to_lankod:
            target_kod = pnr_to_lankod[clean_pnr]
        else:
            # Försök hämta från XML:en (personelementet eller root)
            existing_lankod = person.findtext('LanOchKommun')
            if existing_lankod:
                target_kod = pad_lankod(existing_lankod)
            else:
                target_kod = default_lankod
        
        # Lägg till personen i rätt lista
        grouped_persons[target_kod].append(person)

    # 5. Bygg upp den nya XML-strukturen
    new_root = ET.Element('Lista_lonegranskning')
    
    for lankod, person_list in grouped_persons.items():
        # Skapa en ny <Lonegranskning> för varje unik länkod
        lg_block = ET.SubElement(new_root, 'Lonegranskning')
        
        # Lägg in header-taggarna
        for key, val in header_data.items():
            elem = ET.SubElement(lg_block, key)
            if key == 'Postort':
                # Använd kommunnamn från Excel om det finns, annars originalvärdet
                elem.text = lankod_namn_map.get(lankod, val) # Fallback till original
            else:
                elem.text = val
            
        # Lägg in den specifika Länskoden för denna grupp
        lk_elem = ET.SubElement(lg_block, 'LanOchKommun')
        lk_elem.text = lankod
        
        # Skapa <Personer> blocket och lägg in alla personer som hör hit
        personer_block = ET.SubElement(lg_block, 'Personer')
        for p in person_list:
            personer_block.append(p)

    # 6. Returnera den nya XML:en som en sträng (snyggt formaterad)
    # Python 3.9+ har indent-stöd
    try:
        ET.indent(new_root, space="  ", level=0)
    except AttributeError:
        # Fallback för äldre python versioner om nödvändigt, 
        # men moderna miljöer har 3.9+
        pass
        
    new_tree = ET.ElementTree(new_root)
    
    f = io.BytesIO()
    new_tree.write(f, encoding='ISO-8859-1', xml_declaration=True)
    f.seek(0)
    return f
