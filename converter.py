import xml.etree.ElementTree as ET
import csv
import io
from collections import defaultdict

def clean_personnr(pnr):
    """Tar bort ALLT utom siffror och returnerar de sista 10 siffrorna för robust matchning."""
    if not pnr:
        return ""
    # Behåll endast siffor
    p = "".join(c for c in str(pnr) if c.isdigit())
    # Vi sparar bara de sista 10 siffrorna för att matcha oavsett om XML/CSV har sekel (19/20) eller inte.
    if len(p) >= 10:
        return p[-10:]
    return p

def pad_lankod(kod):
    """Ser till att länskoden alltid är 4 siffror (t.ex. 662 -> 0662)."""
    if not kod:
        return None
    return str(kod).strip().zfill(4)

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

def generate_csv_data(header_data, lankod_namn_map, grouped_persons):
    """Genererar CSV-data baserat på den konverterade XML-strukturen."""
    output = io.StringIO()
    # UTF-8 with BOM for Excel compatibility
    output.write('\ufeff')
    
    # Samla alla unika fältnamn från alla personer för att bygga headers
    # Vi exkluderar vissa fält enligt önskemål
    excluded_fields = {'Arbetsplatsnr', 'UtlanadTillOrgnr', '_original_lankod'}
    
    # Statiska headers från Lonegranskning
    static_headers = ['Postort', 'LanOchKommun', 'LoneperiodStartdatum', 'LoneperiodSlutdatum']
    
    # Hitta alla möjliga Person-fält
    person_fields = []
    seen_person_fields = set()
    
    # Först samla fält för att få en konsekvent ordning
    for lankod, person_list in grouped_persons.items():
        for p in person_list:
            for child in p:
                if child.tag not in seen_person_fields and child.tag not in excluded_fields:
                    seen_person_fields.add(child.tag)
                    person_fields.append(child.tag)
    
    # Sortera person-fälten lite snyggt, Personnummer först om det finns
    if 'Personnummer' in person_fields:
        person_fields.remove('Personnummer')
        person_fields.insert(0, 'Personnummer')
    
    headers = static_headers + person_fields
    
    writer = csv.DictWriter(output, fieldnames=headers, delimiter=';', extrasaction='ignore')
    writer.writeheader()
    
    for lankod, person_list in grouped_persons.items():
        # Värden som är samma för hela denna länkod-grupp
        row_base = {
            'Postort': lankod_namn_map.get(lankod, header_data.get('Postort', '')),
            'LanOchKommun': lankod,
            'LoneperiodStartdatum': header_data.get('LoneperiodStartdatum', ''),
            'LoneperiodSlutdatum': header_data.get('LoneperiodSlutdatum', '')
        }
        
        for p in person_list:
            row = row_base.copy()
            for child in p:
                if child.tag not in excluded_fields:
                    row[child.tag] = child.text
            writer.writerow(row)
            
    return output.getvalue().encode('utf-8-sig')

def _parse_and_group_data(xml_file_streams, csv_file_stream=None, default_lankod="1293", override_start=None, override_end=None):
    # Ladda upp länskods-mappning en gång
    # I en riktig prod-app borde detta cachas, men här är det ok
    lankod_namn_map = load_lankod_map()
    
    # 1. Läs in CSV-filen till en dictionary (om den finns)
    # Mappar Personnummer -> { 'lankod': '...', 'yrkeskod': '...', 'fordelningstal': '...' }
    pnr_to_csv_data = {}
    
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

        # Skapa en mappning för att hitta kolumnnamn oberoende av case/whitespace
        sample_row = csv_rows[0] if csv_rows else {}
        headers_normalized = {k.strip().lower(): k for k in sample_row.keys()}
        
        def get_csv_val(row, *aliases):
            for alias in aliases:
                norm_alias = alias.lower()
                if norm_alias in headers_normalized:
                    return row.get(headers_normalized[norm_alias], '')
            return ''

        for row in csv_rows:
            # Hantera fall där CSV kanske har andra kolumnnamn eller whitespace
            # Struktur: Anst.id;Namn;Län och kommun;Personnr;Yrkeskod;Fördelningstal;
            pnr_raw = get_csv_val(row, 'Personnr', 'Personnummer', 'Pnr', 'Person nr', 'Social Security')
            lankod_raw = get_csv_val(row, 'Län och kommun', 'Länkod', 'Lankod', 'Kommun', 'Län')
            yrkeskod_raw = get_csv_val(row, 'Yrkeskod', 'Yrke', 'Yrkes-kod', 'Profession', 'Job description', 'B_YRKESKOD')
            fordelningstal_raw = get_csv_val(row, 'Fördelningstal', 'Fordelningstal', 'F-tal', 'Fördelning', 'B_FORDELNINGSTAL')
            
            pnr = clean_personnr(pnr_raw)
            lankod = pad_lankod(lankod_raw)
            
            if pnr:
                pnr_to_csv_data[pnr] = {
                    'lankod': lankod,
                    'yrkeskod': yrkeskod_raw.strip() if yrkeskod_raw else None,
                    'fordelningstal': fordelningstal_raw.strip() if fordelningstal_raw else None
                }

    # 2. Parsa XML-filerna (Konteks filer)
    # ... (kod för XML-parsing) ...
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
                
                # Applicera override om de finns
                if override_start:
                    # Ta bort bindestreck om de kommer från HTML date input (YYYY-MM-DD -> YYYYMMDD)
                    header_data['LoneperiodStartdatum'] = override_start.replace('-', '')
                if override_end:
                    header_data['LoneperiodSlutdatum'] = override_end.replace('-', '')
            
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
    # ... (Samma merge logik) ...
    fields_to_sum = [
        'ArbetadeTimmar', 'GrundlonPerTimma', 'UtbNivaPerTimma', 
        'UtbetaltOverskott', 'Lonesumma', 'OBTillagg', 
        'AvtalsenligManadslon', 'Overtidstimmar', 'Overtidstillagg', 
        'Rolltillagg', 'Aktivitetstillagg', 'Kompetenstillagg', 
        'Ansvarstillagg'
    ]
    fields_to_max = ['Fordelningstal']
    
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
                elem_exist = existing_person.find(field)
                elem_new = person.find(field)
                
                if elem_new is not None:
                    if elem_exist is not None:
                        try:
                            val1 = float(elem_exist.text or 0)
                            val2 = float(elem_new.text or 0)
                            elem_exist.text = "{:.2f}".format(val1 + val2)
                        except ValueError:
                            pass
                    else:
                        # Om fältet saknas i den första personen men finns i den nya, lägg till det
                        new_elem = ET.SubElement(existing_person, field)
                        new_elem.text = elem_new.text

            # Special merge för Yrkeskod och Fordelningstal (om de saknas i basen men finns i efterföljande)
            for field in ['Yrkeskod', 'Fordelningstal']:
                base_elem = existing_person.find(field)
                new_elem = person.find(field)
                base_val = base_elem.text.strip() if base_elem is not None and base_elem.text else ""
                
                if (not base_val or base_val == "0") and new_elem is not None and new_elem.text:
                    new_val = new_elem.text.strip()
                    if new_val and new_val != "0":
                        if base_elem is None:
                            base_elem = ET.SubElement(existing_person, field)
                        base_elem.text = new_val
        else:
            # Första gången vi ser personen, spara den
            merged_persons_map[clean_pnr] = person
            # Säkra att Fordelningstal är heltal även här
            ft_elem = person.find('Fordelningstal')
            if ft_elem is not None and ft_elem.text:
                try:
                    ft_elem.text = str(int(float(ft_elem.text)))
                except ValueError:
                    pass
            
    # Uppdatera listan med unika personer
    unique_persons = list(merged_persons_map.values())

    # 3.5 Fallback för Yrkeskod och Fördelningstal från CSV
    for person in unique_persons:
        pnr_xml = person.findtext('Personnummer')
        clean_pnr = clean_personnr(pnr_xml)
        
        if clean_pnr in pnr_to_csv_data:
            csv_data = pnr_to_csv_data[clean_pnr]
            
            # Fallback för Yrkeskod
            yrkeskod_elem = person.find('Yrkeskod')
            current_yrkeskod = yrkeskod_elem.text.strip() if yrkeskod_elem is not None and yrkeskod_elem.text else ""
            if (not current_yrkeskod or current_yrkeskod == "0") and csv_data['yrkeskod']:
                if yrkeskod_elem is None:
                    yrkeskod_elem = ET.SubElement(person, 'Yrkeskod')
                yrkeskod_elem.text = str(csv_data['yrkeskod']).strip()
            
            # Fallback för Fordelningstal
            ford_elem = person.find('Fordelningstal')
            current_ford = ford_elem.text.strip() if ford_elem is not None and ford_elem.text else "0"
            is_empty_or_zero = current_ford == "0" or not current_ford
            
            if is_empty_or_zero and csv_data['fordelningstal']:
                if ford_elem is None:
                    ford_elem = ET.SubElement(person, 'Fordelningstal')
                try:
                    # Säkra att det blir ett heltal
                    val = int(float(str(csv_data['fordelningstal']).strip()))
                    ford_elem.text = str(val)
                except ValueError:
                    ford_elem.text = str(csv_data['fordelningstal']).strip()

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
        if clean_pnr in pnr_to_csv_data and pnr_to_csv_data[clean_pnr]['lankod']:
            target_kod = pnr_to_csv_data[clean_pnr]['lankod']
        else:
            # Försök hämta från XML:en (personelementet eller root)
            existing_lankod = person.findtext('LanOchKommun')
            if existing_lankod:
                target_kod = pad_lankod(existing_lankod)
            else:
                target_kod = default_lankod
        
        # Lägg till personen i rätt lista
        grouped_persons[target_kod].append(person)

    return header_data, lankod_namn_map, grouped_persons

def analyze_bygglosen_data(xml_file_streams, csv_file_stream=None):
    header_data, _, grouped_persons = _parse_and_group_data(
        xml_file_streams, csv_file_stream
    )
    
    warnings = []
    
    # Check if header is missing avtalsomrade
    header_avtal = header_data.get('Avtalsomrade', '').strip() if header_data else ''
    
    for lankod, person_list in grouped_persons.items():
        for person in person_list:
            missing = []
            
            # Check fordelningstal
            ft_elem = person.find('Fordelningstal')
            ft_text = ft_elem.text.strip() if ft_elem is not None and ft_elem.text else "0"
            try:
                if float(ft_text) <= 0:
                    missing.append("Fördelningstal")
            except (ValueError, TypeError):
                missing.append("Fördelningstal")
                
            # Check avtalsomrade
            ao_elem = person.find('Avtalsomrade')
            has_ao = False
            if ao_elem is not None and ao_elem.text and ao_elem.text.strip():
                has_ao = True
            elif header_avtal:
                # Fallback to header
                has_ao = True
                
            if not has_ao:
                missing.append("Avtalsområde")
                
            if missing:
                pnr = person.findtext('Personnummer') or 'Okänt'
                namn = person.findtext('Namn')
                if not namn:
                    fornamn = person.findtext('Fornamn') or ''
                    efternamn = person.findtext('Efternamn') or ''
                    namn = f"{fornamn} {efternamn}".strip()
                if not namn:
                    namn = "Okänt namn"
                    
                warnings.append({
                    "pnr": clean_personnr(pnr),
                    "namn": namn,
                    "missing": missing
                })
                
    return warnings

def convert_bygglosen_data(xml_file_streams, csv_file_stream=None, default_lankod="1293", include_csv=False, override_start=None, override_end=None):
    """
    Konverterar data från XML och CSV streams.
    xml_file_streams: list of file-like objects (binary or text depending on parsing needs)
    csv_file_stream: file-like object (text mode preferable) - OPTIONAL
    
    Om csv_file_stream är None, används länkoderna som redan finns i XML-filerna.
    
    include_csv: Om True, returnera både XML och CSV streams.
    
    override_start/end: Valfria datum (str eller None) som ersätter LoneperiodStartdatum/Slutdatum.
    
    Returnerar antingen:
    - xml_stream (om include_csv=False)
    - (xml_stream, csv_stream) (om include_csv=True)
    """
    header_data, lankod_namn_map, grouped_persons = _parse_and_group_data(
        xml_file_streams, csv_file_stream, default_lankod, override_start, override_end
    )

    # 5. Bygg upp den nya XML-strukturen
    new_root = ET.Element('Lista_lonegranskning')
    
    for lankod, person_list in grouped_persons.items():
        # FILTER: Exclude persons with Fordelningstal 0 from XML
        xml_person_list = []
        for p in person_list:
            ft_elem = p.find('Fordelningstal')
            ft_text = ft_elem.text.strip() if ft_elem is not None and ft_elem.text else "0"
            try:
                # Include only if > 0
                if float(ft_text) > 0:
                    xml_person_list.append(p)
            except (ValueError, TypeError):
                pass
        
        # If no persons left in this group, skip the entire Lonegranskning block for XML
        if not xml_person_list:
            continue

        # Skapa en ny <Lonegranskning> för varje unik länkod
        lg_block = ET.SubElement(new_root, 'Lonegranskning')
        
        # Lägg in header-taggarna i en specifik ordning enligt Byggnads önskemål
        header_keys = [
            'Organisationsnummer', 'Foretagsnamn', 'LoneperiodStartdatum', 
            'LoneperiodSlutdatum', 'Avtalsomrade', 'Lonetyp'
        ]
        
        for key in header_keys:
            val = header_data.get(key, '')
            elem = ET.SubElement(lg_block, key)
            elem.text = val
            
        # LanOchKommun SKA ligga före Postort
        lk_elem = ET.SubElement(lg_block, 'LanOchKommun')
        lk_elem.text = lankod
        
        po_elem = ET.SubElement(lg_block, 'Postort')
        # Använd kommunnamn från Excel om det finns, annars originalvärdet från header_data
        po_elem.text = lankod_namn_map.get(lankod, header_data.get('Postort', ''))
            
        # Skapa <Personer> blocket och lägg in alla personer som hör hit
        personer_block = ET.SubElement(lg_block, 'Personer')
        for p in xml_person_list:
            # Ta bort det interna attributet innan vi lägger till personen i det nya blocket
            if '_original_lankod' in p.attrib:
                del p.attrib['_original_lankod']
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
    
    xml_io = io.BytesIO()
    new_tree.write(xml_io, encoding='ISO-8859-1', xml_declaration=True)
    xml_io.seek(0)
    
    if include_csv:
        csv_data = generate_csv_data(header_data, lankod_namn_map, grouped_persons)
        csv_io = io.BytesIO(csv_data)
        return xml_io, csv_io
        
    return xml_io
