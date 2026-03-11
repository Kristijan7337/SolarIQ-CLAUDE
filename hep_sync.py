"""
HEP Sync - automatsko dohvaćanje interval podataka
Dohvaća P+ i P- za sve dostupne mjesece od 01.2026, preskače postojeće.
Prima username i password kao CLI argumente (za cloud) ili koristi hardkodirane.
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

# ── KONFIGURACIJA ──────────────────────────────────────────
USERNAME = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HEP_USERNAME", "")
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("HEP_PASSWORD", "")
_BAZA_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", _BAZA_DIR)
IZLAZNI_FOLDER = os.path.join(_DATA_DIR, "hep_podaci")
POCETAK_OD = "01.2026"
# ───────────────────────────────────────────────────────────

def fajl_postoji(mjesec, smjer):
    naziv = os.path.join(IZLAZNI_FOLDER, f"{mjesec.replace('.', '-')}_{smjer}.xls")
    return os.path.exists(naziv), naziv

def zatvori_dialog(page):
    try:
        page.wait_for_selector("text=POGREŠKA", timeout=2000)
        page.get_by_role("button", name="OK").click()
        time.sleep(0.3)
        return True
    except:
        return False

def odaberi_smjer(page, smjer):
    page.locator("mat-select[name='vrsteOmm']").click()
    time.sleep(0.3)
    page.get_by_role("option", name=smjer, exact=True).click()
    time.sleep(0.5)

def odaberi_mjesec(page, mjesec):
    page.locator("mat-select[name='period']").click()
    time.sleep(0.3)
    page.get_by_role("option", name=mjesec, exact=True).click()
    time.sleep(1.5)

def skini_fajl(page, mjesec, smjer, smjer_naziv, putanja):
    odaberi_smjer(page, smjer)
    odaberi_mjesec(page, mjesec)

    if zatvori_dialog(page):
        print(f"    – Nema podataka za {mjesec} {smjer}")
        return False

    try:
        with page.expect_download(timeout=30000) as download_info:
            page.get_by_role("button", name="export", exact=True).click()
            time.sleep(1)
            if zatvori_dialog(page):
                print(f"    – Nema podataka za {mjesec} {smjer}")
                return False

        download = download_info.value
        download.save_as(putanja)
        print(f"    → Spremljeno: {os.path.basename(putanja)}", flush=True)
        return True

    except Exception as e:
        if zatvori_dialog(page):
            print(f"    – Nema podataka za {mjesec} {smjer}")
        else:
            print(f"    ✗ Greška za {mjesec} {smjer}: {e}", flush=True)
        return False

def run(username=None, password=None):
    if username is None:
        username = USERNAME
    if password is None:
        password = PASSWORD

    os.makedirs(IZLAZNI_FOLDER, exist_ok=True)

    headless = os.environ.get('RENDER') == 'true' or os.environ.get('HEADLESS') == '1'

    with sync_playwright() as p:
        launch_args = ['--no-sandbox', '--disable-dev-shm-usage']
        if not headless:
            launch_args.append('--window-position=-32000,-32000')

        browser = p.chromium.launch(headless=headless, args=launch_args)
        context = browser.new_context()
        page = context.new_page()

        # LOGIN
        print("Logiram se...", flush=True)
        page.goto("https://mjerenje.hep.hr/mjerenja/login")
        page.get_by_role("textbox", name="Korisničko ime").fill(username)
        page.get_by_role("textbox", name="Lozinka").fill(password)
        page.get_by_role("button", name="Prijava").click()
        page.wait_for_selector("button:has-text('export')", timeout=15000)
        print("Login uspješan!", flush=True)
        time.sleep(2)

        # Dohvati dostupne mjesece
        page.locator("mat-select[name='period']").click()
        time.sleep(0.5)
        sve_opcije = page.locator("mat-option").all_text_contents()
        page.keyboard.press("Escape")
        time.sleep(0.5)

        def kao_datum(s):
            parts = s.strip().split('.')
            return f"{parts[1]}-{parts[0]}"

        pocetak = kao_datum(POCETAK_OD)
        opcije = [o for o in sve_opcije if kao_datum(o.strip()) >= pocetak]
        print(f"Filtriranih mjeseci: {len(opcije)} ( {opcije[0]}  →  {opcije[-1]} )", flush=True)

        ukupno = 0
        preskoceno = 0

        from datetime import datetime
        now = datetime.now()
        tekuci_hep = f"{str(now.month).zfill(2)}.{now.year}"

        for mjesec in opcije:
            mjesec = mjesec.strip()
            print(f"\n── {mjesec} ──", flush=True)
            je_tekuci = (mjesec == tekuci_hep)

            for smjer, smjer_naziv in [("P+", "A_plus"), ("P-", "A_minus")]:
                postoji, putanja = fajl_postoji(mjesec, smjer_naziv)
                if postoji and not je_tekuci:
                    print(f"  ✓ {smjer} već postoji", flush=True)
                    preskoceno += 1
                    continue
                if je_tekuci and postoji:
                    import datetime as _dt
                    mtime = _dt.date.fromtimestamp(os.path.getmtime(putanja))
                    if mtime == _dt.date.today():
                        print(f"  ✓ {smjer} tekući - već skinuto danas", flush=True)
                        preskoceno += 1
                        continue
                    print(f"  ↻ {smjer} tekući mjesec - osvježavam", flush=True)
                    os.remove(putanja)

                uspjeh = skini_fajl(page, mjesec, smjer, smjer_naziv, putanja)
                if uspjeh:
                    ukupno += 1
                else:
                    preskoceno += 1

                time.sleep(0.5)

        browser.close()

    print(f"\nGotovo! Preuzeto: {ukupno}, Preskočeno: {preskoceno}", flush=True)
    print(f"Fajlovi su u: {IZLAZNI_FOLDER}", flush=True)

if __name__ == "__main__":
    run()
