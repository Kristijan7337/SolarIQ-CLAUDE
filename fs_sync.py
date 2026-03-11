"""
FusionSolar Sync - automatsko dohvaćanje Plant Report podataka
"""

import os
import sys
import time
import glob
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── KONFIGURACIJA ──────────────────────────────────────────
FS_USERNAME = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FS_USERNAME", "")
FS_PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("FS_PASSWORD", "")
BAZA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BAZA_DIR)
PODACI_DIR = os.path.join(DATA_DIR, "fs_podaci")
POCETAK_OD = "2026-01"
# ───────────────────────────────────────────────────────────

def get_missing_months():
    now = datetime.now()
    tekuci = f"{now.year}-{str(now.month).zfill(2)}"
    kraj = tekuci
    
    sve = []
    y, m = map(int, POCETAK_OD.split('-'))
    ky, km = map(int, kraj.split('-'))
    while (y, m) <= (ky, km):
        ym = f"{y}-{str(m).zfill(2)}"
        pattern = os.path.join(PODACI_DIR, f"*{ym}*.xlsx")
        # Prošle mjesece samo ako nedostaju, tekući samo ako nije već skinuto danas
        existing = glob.glob(pattern)
        if not existing:
            sve.append(ym)
        elif ym == tekuci:
            import datetime as _dt
            mtime = _dt.date.fromtimestamp(os.path.getmtime(existing[0]))
            if mtime < _dt.date.today():
                sve.append(ym)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return sve

def run():
    os.makedirs(PODACI_DIR, exist_ok=True)

    missing = get_missing_months()
    if not missing:
        print("✓ Fusion Solar podaci su ažurni")
        return

    print(f"Nedostaju FS podaci za: {', '.join(missing)}")

    with sync_playwright() as p:
        headless = os.environ.get('RENDER') == 'true' or os.environ.get('HEADLESS') == '1' or not os.environ.get('DISPLAY')
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context().new_page()

        # ── LOGIN ──
        print("Logiram se na Fusion Solar...")
        page.goto("https://eu5.fusionsolar.huawei.com/unisso/login.action")
        time.sleep(5)

        # Unesi username i password
        page.get_by_placeholder("Username/Email").fill(FS_USERNAME)
        time.sleep(0.5)
        page.get_by_placeholder("Password").fill(FS_PASSWORD)
        time.sleep(0.5)
        
        # Klikni login gumb - probaj više selektora
        try:
            page.locator("#submitDataverify").click(timeout=5000)
        except:
            try:
                page.locator(".btn_outerverify").click(timeout=5000)
            except:
                page.locator(".login-btn, .btn-login, button").first.click(timeout=5000)
        
        # Čekaj login
        print("Čekam login...")
        page.wait_for_url("**/pvmswebsite/**", timeout=30000)
        print("Login uspješan!")
        time.sleep(3)

        # ── NAVIGACIJA DO PLANT REPORT ──
        print("Navigiram do Plant Report...")
        page.goto("https://uni001eu5.fusionsolar.huawei.com/uniportal/pvmswebsite/assets/build/cloud.html?app-id=smartpvms&instance-id=smartpvms&zone-id=region-1-43b6d703-7da9-49f0-8b84-048ff489273f#/view/station/NE=195805630/report")
        page.wait_for_load_state("networkidle")
        time.sleep(8)
        print(f"URL na Plant Report: {page.url}")
        # Čekaj dropdown
        page.locator(".dpdesign-select-selection-item").first.wait_for(timeout=60000)
        time.sleep(2)

        ukupno = 0

        for ym in missing:
            print(f"  ↓ Dohvaćam {ym}...")
            try:
                # Odaberi "By Month" iz dropdowna - samo ako nije već odabrano
                current = page.locator(".dpdesign-select-selection-item").first.get_attribute("title") or ""
                if "month" not in current.lower():
                    page.locator(".dpdesign-select-selection-item").first.click(timeout=5000)
                    time.sleep(0.5)
                    try:
                        page.get_by_text("By month").click(timeout=3000)
                    except:
                        page.get_by_title("By month").click(timeout=3000)
                    time.sleep(1)

                # Unesi period
                period_input = page.locator("input[placeholder*='month'], input[placeholder*='Month'], input[placeholder*='period']").first
                period_input.click()
                period_input.press("Control+a")
                period_input.fill(ym)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(1)

                # Query
                page.locator(".dpdesign-btn-primary").first.click(timeout=5000)
                time.sleep(3)

                # Export - klikni Export gumb
                try:
                    page.get_by_role("button", name="Export").click(timeout=5000)
                except:
                    page.locator("button:has-text('Export')").click(timeout=5000)
                time.sleep(3)

                # Čekaj Tasks modal i klikni download za prvi red
                page.wait_for_selector("[data-icon='download']", timeout=15000)
                time.sleep(1)
                
                putanja = os.path.join(PODACI_DIR, f"Plant_Report_{ym}.xlsx")
                with page.expect_download(timeout=15000) as dl:
                    page.locator("[data-icon='download']").first.click(timeout=5000)
                
                dl.value.save_as(putanja)
                print(f"    → Spremljeno: Plant_Report_{ym}.xlsx")
                ukupno += 1
                
                # Zatvori Tasks modal - probaj više selektora i čekaj da se zatvori
                for sel in [
                    ".dpdesign-modal-close",
                    "[aria-label='Close']",
                    "button.dpdesign-modal-close",
                    ".dpdesign-modal-header button",
                    "button:has-text('×')",
                    "button:has-text('X')"
                ]:
                    try:
                        page.locator(sel).first.click(timeout=2000)
                        # Čekaj da modal nestane
                        page.wait_for_selector(".dpdesign-modal-title-with-close", state="hidden", timeout=5000)
                        break
                    except:
                        continue
                time.sleep(1)

            except Exception as e:
                print(f"    ✗ Greška za {ym}: {e}")
                time.sleep(1)

        browser.close()

    print(f"\nGotovo! Preuzeto: {ukupno} Fusion Solar izvještaja")

if __name__ == "__main__":
    run()
