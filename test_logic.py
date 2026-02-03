
import os
import io

def generate_dummy_files():
    # Create a dummy CSV
    csv_content = """Personnr;Län och kommun
19900101-1234;0662
19920202-5678;1280
"""
    
    # Create a dummy XML (Konteks-like structure)
    xml_content = """<?xml version="1.0" encoding="ISO-8859-1"?>
<Lonerapport>
  <Lonegranskning>
    <Organisationsnummer>556000-0000</Organisationsnummer>
    <Foretagsnamn>Testbolaget AB</Foretagsnamn>
    <LoneperiodStartdatum>2023-10-01</LoneperiodStartdatum>
    <LoneperiodSlutdatum>2023-10-31</LoneperiodSlutdatum>
    <Avtalsomrade>Bygg</Avtalsomrade>
    <Lonetyp>Timlon</Lonetyp>
    <Postort>Teststad</Postort>
    <Personer>
      <Person>
        <Personnummer>199001011234</Personnummer>
        <Namn>Anders Andersson</Namn>
        <Lon>30000</Lon>
      </Person>
      <Person>
        <Personnummer>199202025678</Personnummer>
        <Namn>Bertil Bengtsson</Namn>
        <Lon>32000</Lon>
      </Person>
       <Person>
        <Personnummer>198001019999</Personnummer>
        <Namn>Cecilia Carlsson</Namn>
        <Lon>35000</Lon>
      </Person>
    </Personer>
  </Lonegranskning>
</Lonerapport>
"""
    return csv_content, xml_content

def test_conversion():
    from converter import convert_bygglosen_data
    import csv
    
    csv_str, xml_str = generate_dummy_files()
    
    # Simulate file streams
    csv_stream = io.BytesIO(csv_str.encode('utf-8'))
    xml_stream = io.BytesIO(xml_str.encode('iso-8859-1'))
    
    print("Testing conversion logic directly (XML only)...")
    try:
        result_stream = convert_bygglosen_data(xml_stream, csv_stream)
        result_content = result_stream.getvalue().decode('iso-8859-1')
        
        if "0662" in result_content and "1280" in result_content:
            print("SUCCESS: Found expected LanOchKommun codes in XML output.")
        else:
            print("FAILURE: expected codes not found in XML.")
            
    except Exception as e:
        print(f"FAILURE: Exception occurred during XML test: {e}")

    # Reset streams or recreate them
    csv_stream = io.BytesIO(csv_str.encode('utf-8'))
    xml_stream = io.BytesIO(xml_str.encode('iso-8859-1'))
    
    print("\nTesting conversion logic (XML + CSV)...")
    try:
        xml_res, csv_res = convert_bygglosen_data(xml_stream, csv_stream, include_csv=True)
        csv_content = csv_res.getvalue().decode('utf-8-sig')
        
        print("\n--- Result CSV Start ---")
        print(csv_content[:500])
        print("--- Result CSV End ---")
        
        # Check for headers
        expected_headers = ['Postort', 'LanOchKommun', 'LoneperiodStartdatum', 'LoneperiodSlutdatum', 'Personnummer', 'Namn', 'Lon']
        for header in expected_headers:
            if header not in csv_content:
                print(f"FAILURE: Header '{header}' missing in CSV.")
            else:
                print(f"SUCCESS: Found header '{header}'.")
        
        # Check for data
        if "199001011234" in csv_content and "0662" in csv_content:
            print("SUCCESS: Found person data and lankod in CSV.")
        else:
            print("FAILURE: Person data or lankod missing in CSV.")
            
    except Exception as e:
        print(f"FAILURE: Exception occurred during CSV test: {e}")

if __name__ == "__main__":
    test_conversion()
