# Bygglösen Konverterare

Flask-baserad webbapplikation för konvertering av lönegranskningsfiler från Konteks-format till Byggnads-format. Hanterar sammanslagning av multipla XML-filer, länkodsmatchning och export till XML och CSV.

---

## Innehåll

- [Vad applikationen gör](#vad-applikationen-gör)
- [Dataflöde och datahantering](#dataflöde-och-datahantering)
- [Filstruktur](#filstruktur)
- [Dependencies](#dependencies)
- [Miljövariabler](#miljövariabler)
- [Autentisering (Clerk)](#autentisering-clerk)
- [Köra lokalt](#köra-lokalt)
- [Driftsättning](#driftsättning)
- [Azure Container Apps](#azure-container-apps)

---

## Vad applikationen gör

Användaren laddar upp en eller flera **XML-filer** (Konteks Lönegranskning-format) och eventuellt en **CSV-fil** med personnummer och länkoder. Applikationen:

1. Parsar alla XML-filer och slår ihop poster för samma personnummer
2. Matchar personnummer mot CSV-filen för att berika med länkod, yrkeskod och fördelningstal
3. Grupperar anställda per länkod
4. Producerar en ny XML-fil i Byggnads-format, med ett `<Lonegranskning>`-block per länkod
5. Kan även exportera samma data som CSV (semicolonseparerad, UTF-8 BOM för Excel-kompatibilitet)
6. Output levereras direkt som nedladdning – antingen en enskild XML-fil eller en ZIP med XML + CSV

### Indata

| Fil | Format | Obligatorisk |
|-----|--------|-------------|
| Lönegranskning XML (Konteks) | XML | Ja (1 eller flera) |
| Person/Länkod CSV | Semikolonseparerad CSV | Nej |

### Utdata

| Scenario | Output |
|----------|--------|
| Endast XML | `LOSEN_konverterad_[tidsstämpel].xml` |
| XML + CSV | `LOSEN_export_[tidsstämpel].zip` med båda filerna |

### Datumkontroll

Vid uppladdning av XML-filer analyserar sidan automatiskt `<LoneperiodStartdatum>` och `<LoneperiodSlutdatum>` i varje fil (client-side, läser de första 10 KB). Om datumen ter sig felaktiga (t.ex. start = slut) visas en varning och användaren kan justera dem innan konvertering.

---

## Dataflöde och datahantering

### Dataintegritet

> **Ingen data lagras på servern.**
> Uppladdade filer bearbetas uteslutande i minnet (Python `io.BytesIO`/`io.StringIO`) och raderas när HTTP-anropet är klart. Det finns ingen databas, ingen fillagring, inget loggande av filinnehåll.

### Konverteringslogik (`converter.py`)

#### 1. XML-parsning och headerinsamling
- Parsar varje XML med `xml.etree.ElementTree`
- Hämtar metadata (org.nr, företagsnamn, löneperiod, avtalsområde) från **första filen**
- Löneperioddatum kan overridas av användaren

#### 2. Sammanslagning av dubbletter
Samma personnummer kan förekomma i flera XML-filer (t.ex. vid säsongsskifte). Dessa slås ihop:

| Fält | Hantering |
|------|-----------|
| `ArbetadeTimmar`, `Lonesumma`, `OBTillagg`, `Overtidstimmar` m.fl. | Summeras (float-addition) |
| `Fordelningstal` | Max-värde (högst icke-noll-värde vinner) |
| `Yrkeskod`, `Fordelningstal` | Fallback: värde från CSV om XML saknar/har 0 |

Personnummermatching är robust: endast de sista 10 siffrorna används, alla icke-siffror tas bort, vilket hanterar skiljetecken och sekelprefix (19/20).

#### 3. Länkodsmatchning
Länkoder hanteras i prioritetsordning:
1. **CSV-filen** (om uppladdad och personnumret finns)
2. **Befintlig `<LanOchKommun>` i XML-filen**
3. **Default-länkod** `1293` (hårdkodad fallback)

Länkoderna nollpadadas alltid till 4 siffror (`662` → `0662`).

#### 4. Kommunnamnsuppslagning
`kommunlankod-2026.xlsx` innehåller en tabell med länkod → kommunnamn. Denna läses med `openpyxl` och används för att sätta `<Postort>` i output-XML. Filen ingår i repot och kopieras in i Docker-imagen.

#### 5. Output-XML-format
```xml
<Lista_lonegranskning>
  <Lonegranskning>
    <Organisationsnummer>...</Organisationsnummer>
    <Foretagsnamn>...</Foretagsnamn>
    <LoneperiodStartdatum>YYYYMMDD</LoneperiodStartdatum>
    <LoneperiodSlutdatum>YYYYMMDD</LoneperiodSlutdatum>
    <Avtalsomrade>...</Avtalsomrade>
    <Lonetyp>...</Lonetyp>
    <LanOchKommun>XXXX</LanOchKommun>
    <Postort>Kommunnamn</Postort>
    <Personer>
      <Person>...</Person>
    </Personer>
  </Lonegranskning>
  <!-- ett block per unik länkod -->
</Lista_lonegranskning>
```
Output kodas som **ISO-8859-1** med XML-deklaration.

#### 6. CSV-export
- Semicolonseparerad
- UTF-8 med BOM (för direkt öppning i Excel)
- Kolumner: `Postort`, `LanOchKommun`, `LoneperiodStartdatum`, `LoneperiodSlutdatum` + alla personfält

---

## Filstruktur

```
bygglosen-converter/
├── app.py                          # Flask-app, routes, Clerk-auth
├── converter.py                    # Hela konverteringslogiken
├── kommunlankod-2026.xlsx          # Länkod → kommunnamn-tabell
├── test_logic.py                   # Enhetstester för konverteringslogiken
├── requirements.txt                # Python-paket
├── Dockerfile                      # Container-definition
├── Procfile                        # Heroku/Railway fallback-startkommando
├── railway.json                    # Railway-konfiguration
├── .env.example                    # Mall för miljövariabler
├── .gitignore
└── templates/
    ├── index.html                  # Huvud-UI med Clerk JS och formulär
    └── admin.html                  # Adminvy (kräver ADMIN_EMAIL)
```

---

## Dependencies

### Python-paket (`requirements.txt`)

| Paket | Version | Syfte |
|-------|---------|-------|
| `flask` | 3.1.0 | Webbframework |
| `gunicorn` | 23.0.0 | WSGI-server för produktion |
| `openpyxl` | 3.1.5 | Läsning av `kommunlankod-2026.xlsx` |
| `python-dotenv` | 1.1.0 | Laddar `.env`-fil vid lokal körning |
| `clerk-backend-api` | 5.0.2 | Verifiering av Clerk-sessionstoken i backend |

**Transativa beroenden** (installeras automatiskt):

| Paket | Syfte |
|-------|-------|
| `httpx` | HTTP-klient (används av Clerk SDK) |
| `pydantic` / `pydantic-core` | Datavalidering (Clerk SDK) |
| `PyJWT` | JWT-tokenhantering (Clerk SDK) |
| `anyio` / `httpcore` | Asynkron I/O (Clerk SDK) |
| `Werkzeug` | WSGI-utilities (Flask) |

### Frontend

| Bibliotek | Leverans | Syfte |
|-----------|---------|-------|
| `@clerk/clerk-js` | CDN (Clerk's egna servrar) | Inloggnings-UI och sessionshantering |

Inga andra frontend-bibliotek, ramverk eller build-steg krävs. All styling är vanilla CSS inbäddad i `index.html`.

---

## Miljövariabler

| Variabel | Obligatorisk | Beskrivning |
|----------|-------------|-------------|
| `CLERK_PUBLISHABLE_KEY` | Ja | Clerk publishable key (`pk_test_...` eller `pk_live_...`) |
| `CLERK_SECRET_KEY` | Ja | Clerk secret key (`sk_test_...` eller `sk_live_...`) |
| `SECRET_KEY` | Ja | Flask session secret – godtycklig slumpmässig sträng |
| `ADMIN_EMAIL` | Nej | E-post som ges tillgång till `/admin`. Lämna tom för att inaktivera. |
| `CLERK_AUTHORIZED_PARTY` | Nej | Applikationens URL för JWT `azp`-validering. Kan lämnas tom. |

---

## Autentisering (Clerk)

Applikationen använder [Clerk](https://clerk.com) för autentisering.

### Flöde

```
Browser                          Flask-backend
  │                                    │
  ├─ Clerk JS laddas från CDN ────────►│
  ├─ Användare klickar "Logga in"      │
  ├─ Clerk-modal öppnas               │
  ├─ Inloggning sker via Clerk         │
  ├─ Clerk sätter __session-cookie     │
  │                                    │
  ├─ POST /convert (med cookie) ──────►│
  │                              clerk_authenticate_request()
  │                              sdk.users.get_user()
  │                              → konvertering körs
  │◄───────────── fil-nedladdning ─────┤
```

### Backend-verifiering

`clerk-backend-api` SDK:s `authenticate_request()` verifierar sessionstoken mot Clerks JWKS-endpoint. Lyckad verifiering ger tillgång till `user_id` varefter användarinfo hämtas från Clerk API.

Skyddade routes: `/convert`, `/admin`  
Öppna routes: `/`

### Admin-åtkomst

Om `ADMIN_EMAIL` är satt visas en adminlänk för den inloggade användaren med matchande e-post. Adminvyn listar alla användare via Clerk API (ingen lokal databas).

---

## Köra lokalt

```bash
# Klona repot
git clone https://github.com/Friggo-74/bygglosen-converter
cd bygglosen-converter

# Skapa virtuell miljö
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # macOS/Linux

# Installera paket
pip install -r requirements.txt

# Skapa .env-fil
copy .env.example .env
# Fyll i CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, SECRET_KEY

# Starta
python app.py
# Öppna http://localhost:5000
```

### Tester

```bash
python -m pytest test_logic.py -v
```

Testerna täcker konverteringslogiken i `converter.py` och kräver ingen Clerk-konfiguration.

---

## Driftsättning

### Railway (nuvarande)

Applikationen är konfigurerad för Railway via `Dockerfile` och `railway.json`.

**Viktigt:** Sätt **inte** ett eget startkommando i Railways UI-inställningar – låt Dockerfile:n styra (använder `exec gunicorn --bind :$PORT`).

Miljövariabler sätts under **Service → Variables** i Railway Dashboard.

### Krav för Clerk i produktion

1. Gå till Clerk Dashboard → din applikation
2. Under **Domains** – lägg till din produktions-URL
3. Byt ut `pk_test_` / `sk_test_`-nycklar mot `pk_live_` / `sk_live_`-nycklar

---

## Azure Container Apps

För driftsättning på Azure Container Apps kan befintlig `Dockerfile` användas utan ändringar.

### Steg

```bash
# Bygg och pusha imagen till Azure Container Registry
az acr build --registry <ditt-acr-namn> --image bygglosen-converter:latest .

# Skapa Container App
az containerapp create \
  --name bygglosen-converter \
  --resource-group <din-rg> \
  --environment <din-miljö> \
  --image <ditt-acr-namn>.azurecr.io/bygglosen-converter:latest \
  --target-port 8080 \
  --ingress external \
  --env-vars \
    CLERK_PUBLISHABLE_KEY=pk_live_... \
    CLERK_SECRET_KEY=sk_live_... \
    SECRET_KEY=<slumpmässig-sträng>
```

### Noteringar för Azure

| Punkt | Detalj |
|-------|--------|
| **Port** | Container lyssnar på `$PORT` (default 8080 i Dockerfile) – matchar Azure's standard |
| **Skalning** | `clerk-backend-api` kräver nätverksåtkomst till `clerk.com` för JWKS-hämtning |
| **Secrets** | Miljövariabler kan lagras som Azure Container App Secrets istället för plain-text |
| **Clerk-domän** | Kom ihåg att lägga till Azure-URL:en i Clerk Dashboard → Domains |
| **Hälsokontroll** | Rotvägen `/` returnerar 200 utan auth och passar som health probe |
