
import os
import io

def generate_dummy_files():
    # Create a dummy CSV based on the new structure:
    # Anst.id;Namn;Län och kommun;Personnr;Yrkeskod;Fördelningstal;
    csv_content = """Anst.id;Namn;Län och kommun;Personnr;Yrkeskod;Fördelningstal;
1;Anders Andersson;0662;19900101-1234;123;100;
2;Bertil Bengtsson;1280;19920202-5678;456;80;
3;Cecilia Carlsson;1293;19800101-9999;789;50;
"""
    
    # Create a dummy XML (Konteks-like structure)
    # Cecilia is missing Yrkeskod and Fordelningstal in XML
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
        <Yrkeskod>123</Yrkeskod>
        <Fordelningstal>100</Fordelningstal>
        <Lon>30000</Lon>
      </Person>
      <Person>
        <Personnummer>199202025678</Personnummer>
        <Namn>Bertil Bengtsson</Namn>
        <Yrkeskod>456</Yrkeskod>
        <Fordelningstal>80</Fordelningstal>
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
    
    print("Testing conversion logic (XML + CSV Fallback)...")
    try:
        xml_res, csv_res = convert_bygglosen_data(xml_stream, csv_stream, include_csv=True)
        xml_content = xml_res.getvalue().decode('iso-8859-1')
        csv_content = csv_res.getvalue().decode('utf-8-sig')
        
        # Verify XML Fallback for Cecilia (198001019999)
        if '<Yrkeskod>789</Yrkeskod>' in xml_content and '<Fordelningstal>50</Fordelningstal>' in xml_content:
            print("SUCCESS: Found fallback values (Yrkeskod, Fordelningstal) for Cecilia in XML output.")
        else:
            print("FAILURE: Fallback values for Cecilia missing in XML.")
            
        # Verify CSV export also has the fields
        expected_headers = ['Yrkeskod', 'Fordelningstal']
        for header in expected_headers:
            if header not in csv_content:
                print(f"FAILURE: Header '{header}' missing in CSV export.")
            else:
                print(f"SUCCESS: Found header '{header}' in CSV export.")
        
        if "789" in csv_content and "50" in csv_content:
            print("SUCCESS: Fallback values present in CSV export.")
        else:
            print("FAILURE: Fallback values missing in CSV export.")
            
    except Exception as e:
        print(f"FAILURE: Exception occurred during conversion test: {e}")

if __name__ == "__main__":
    test_conversion()
